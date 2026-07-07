import pdfplumber
import difflib
import html
import re
import io
from dataclasses import dataclass

@dataclass
class ClauseBlock:
    type: str  # "p" or "table"
    content: str

@dataclass
class Clause:
    heading: str
    key: str
    blocks: list[ClauseBlock]

@dataclass
class ComparisonRow:
    index: int
    old_heading: str
    new_heading: str
    old_html: str      
    new_html: str      
    diff_html: str     
    status: str
    similarity: float

class DynamicDocumentParser:
    CODE_RE = re.compile(r"^((?:AMC\d*\s*|GM\d*\s*|CAR\s*)?\d+\s*\.?\s*[A-Z]?\.\d+[A-Z]?(?:\s*\([a-z0-9]+\))*)(?:\s+|$|-)", re.IGNORECASE)

    @staticmethod
    def get_clause_key(text: str) -> str:
        match = DynamicDocumentParser.CODE_RE.search(text)
        if match:
            return re.sub(r"\s+", "", match.group(1).upper())
        return re.sub(r'[^A-Z0-9]', '', text.upper()[:30])

    @staticmethod
    def extract_clauses(file_bytes: bytes) -> list[Clause]:
        clauses_dict = {}
        current_heading = "Document Introduction"
        current_key = "INTRO"
        clauses_dict[current_key] = {"heading": current_heading, "blocks": []}
        
        current_paragraph = []
        prev_bottom = 0
        PARAGRAPH_SPACING_THRESHOLD = 6.0 

        def flush_paragraph():
            nonlocal current_paragraph
            if current_paragraph:
                clean_text = " ".join(current_paragraph)
                clauses_dict[current_key]["blocks"].append(ClauseBlock(type="p", content=clean_text))
                current_paragraph = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                width = page.width
                height = page.height
                bounding_box = (0, height * 0.08, width, height * 0.92)
                cropped_page = page.crop(bounding_box)
                
                page_items = []
                
                #extracting the tables
                tables = cropped_page.find_tables()
                table_bboxes = [t.bbox for t in tables]
                for t in tables:
                    html_table = '<table class="doc-table">'
                    for row in t.extract():
                        html_table += "<tr>"
                        for cell in row:
                            cell_text = str(cell).replace("\n", " ") if cell is not None else ""
                            html_table += f"<td>{html.escape(cell_text)}</td>"
                        html_table += "</tr>"
                    html_table += "</table>"
                    page_items.append({"type": "table", "content": html_table, "top": t.bbox[1], "bottom": t.bbox[3]})
                
                #extracting text lines
                words = cropped_page.extract_words(keep_blank_chars=True)
                filtered_words = []
                for w in words:
                    in_table = any(x0 <= w['x0'] and top <= w['top'] and x1 >= w['x1'] and bottom >= w['bottom'] 
                                   for x0, top, x1, bottom in table_bboxes)
                    if not in_table:
                        filtered_words.append(w)
                
                lines = {}
                for w in filtered_words:
                    line_y = round(w['top'] / 3) * 3 
                    if line_y not in lines: lines[line_y] = []
                    lines[line_y].append(w)
                
                for y in sorted(lines.keys()):
                    line_words = sorted(lines[y], key=lambda x: x['x0'])
                    line_text = " ".join([w['text'] for w in line_words]).strip()
                    if len(line_text) > 2 and not re.match(r"\.{4,}", line_text):
                        top = line_words[0]['top']
                        bottom = max(w['bottom'] for w in line_words)
                        page_items.append({"type": "line", "content": line_text, "top": top, "bottom": bottom})
                
                #structured analysis
                page_items.sort(key=lambda x: x["top"])
                
                for item in page_items:
                    if item["type"] == "table":
                        flush_paragraph()
                        clauses_dict[current_key]["blocks"].append(ClauseBlock(type="table", content=item["content"]))
                        prev_bottom = item["bottom"]
                    
                    elif item["type"] == "line":
                        text = item["content"]
                        if DynamicDocumentParser.CODE_RE.search(text):
                            flush_paragraph()
                            current_heading = text
                            current_key = DynamicDocumentParser.get_clause_key(text)
                            if current_key not in clauses_dict:
                                clauses_dict[current_key] = {"heading": current_heading, "blocks": []}
                            prev_bottom = item["bottom"]
                        else:
                            if current_paragraph:
                                if (item["top"] - prev_bottom) > PARAGRAPH_SPACING_THRESHOLD:
                                    flush_paragraph()
                            current_paragraph.append(text)
                            prev_bottom = item["bottom"]
                            
        flush_paragraph()

        final_clauses = []
        for key, data in clauses_dict.items():
            if data["blocks"]:
                final_clauses.append(Clause(
                    heading=data["heading"],
                    key=key,
                    blocks=data["blocks"]
                ))
                
        return final_clauses

class DiffEngine:
    @staticmethod
    def render_blocks(blocks: list[ClauseBlock]) -> str:
        """Renders raw blocks cleanly without diff marks."""
        out = []
        for b in blocks:
            if b.type == "p":
                out.append(f"<p>{html.escape(b.content)}</p>")
            else:
                out.append(b.content)
        return "".join(out)

    @staticmethod
    def get_similarity(old_blocks: list[ClauseBlock], new_blocks: list[ClauseBlock]) -> float:
        old_text = " ".join([b.content for b in old_blocks if b.type == "p"])
        new_text = " ".join([b.content for b in new_blocks if b.type == "p"])
        if not old_text and not new_text: return 100.0
        if not old_text or not new_text: return 0.0
        return difflib.SequenceMatcher(None, old_text, new_text).ratio() * 100

    @staticmethod
    def word_diff_plain(old_text: str, new_text: str) -> str:
        """Safely diffs plain text. No HTML tags exist here, so it cannot corrupt the DOM."""
        old_tokens = re.findall(r"[\w]+|[^\w\s]|\s+", old_text)
        new_tokens = re.findall(r"[\w]+|[^\w\s]|\s+", new_text)
        matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
        parts = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                parts.append(html.escape("".join(new_tokens[j1:j2])))
            elif tag == "delete":
                parts.append(f'<span class="removed">{html.escape("".join(old_tokens[i1:i2]))}</span>')
            elif tag == "insert":
                parts.append(f'<span class="added">{html.escape("".join(new_tokens[j1:j2]))}</span>')
            elif tag == "replace":
                parts.append(f'<span class="removed">{html.escape("".join(old_tokens[i1:i2]))}</span>')
                parts.append(f'<span class="added">{html.escape("".join(new_tokens[j1:j2]))}</span>')
        return "".join(parts)

    @staticmethod
    def diff_blocks(old_blocks: list[ClauseBlock], new_blocks: list[ClauseBlock]) -> str:
        """Safely diffs block-by-block. Tables are NEVER word-diffed."""
        out = []
        matcher = difflib.SequenceMatcher(
            None, 
            [(b.type, b.content) for b in old_blocks], 
            [(b.type, b.content) for b in new_blocks], 
            autojunk=False
        )
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for b in new_blocks[j1:j2]:
                    if b.type == "p": out.append(f"<p>{html.escape(b.content)}</p>")
                    else: out.append(b.content)
                    
            elif tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1 and old_blocks[i1].type == "p" and new_blocks[j1].type == "p":
                # Only run inline text diff if exactly one paragraph replaces another
                diffed_text = DiffEngine.word_diff_plain(old_blocks[i1].content, new_blocks[j1].content)
                out.append(f"<p>{diffed_text}</p>")
                
            else:
                # For completely different blocks or tables, just stack the old (red) and new (green)
                for b in old_blocks[i1:i2]:
                    if b.type == "p": out.append(f'<p class="removed">{html.escape(b.content)}</p>')
                    else: out.append(f'<div class="removed-table">{b.content}</div>')
                for b in new_blocks[j1:j2]:
                    if b.type == "p": out.append(f'<p class="added">{html.escape(b.content)}</p>')
                    else: out.append(f'<div class="added-table">{b.content}</div>')
                    
        return "".join(out)

    @staticmethod
    def pair_clauses(old_clauses: list[Clause], new_clauses: list[Clause]) -> list[ComparisonRow]:
        old_by_key = {c.key: c for c in old_clauses}
        new_by_key = {c.key: c for c in new_clauses}
        
        all_keys = []
        for c in old_clauses:
            if c.key not in all_keys: all_keys.append(c.key)
        for c in new_clauses:
            if c.key not in all_keys: all_keys.append(c.key)
            
        rows = []
        for idx, key in enumerate(all_keys):
            old_c = old_by_key.get(key)
            new_c = new_by_key.get(key)
            
            old_blocks = old_c.blocks if old_c else []
            new_blocks = new_c.blocks if new_c else []
            
            sim_score = DiffEngine.get_similarity(old_blocks, new_blocks)
            
            if old_c and not new_c: status = "REMOVED"
            elif new_c and not old_c: status = "ADDED"
            elif sim_score == 100.0: status = "UNCHANGED"
            else: status = "CHANGED"
            
            rows.append(ComparisonRow(
                index=idx + 1,
                old_heading=old_c.heading if old_c else "",
                new_heading=new_c.heading if new_c else "",
                old_html=DiffEngine.render_blocks(old_blocks),
                new_html=DiffEngine.render_blocks(new_blocks),
                diff_html=DiffEngine.diff_blocks(old_blocks, new_blocks) if status == "CHANGED" else "",
                status=status,
                similarity=sim_score
            ))
            
        return rows