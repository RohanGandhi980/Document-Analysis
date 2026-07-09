import pdfplumber
import difflib
import html
import re
import io
from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

@dataclass
class ClauseBlock:
    type: str  
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
        out = []
        for b in blocks:
            if b.type == "p":
                out.append(f"<p>{html.escape(b.content)}</p>")
            else:
                out.append(b.content)
        return "".join(out)

    @staticmethod
    def get_plain_text(blocks: list[ClauseBlock]) -> str:
        return " ".join([b.content for b in blocks if b.type == "p"])

    @staticmethod
    def word_diff_plain(old_text: str, new_text: str) -> str:
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
                diffed_text = DiffEngine.word_diff_plain(old_blocks[i1].content, new_blocks[j1].content)
                out.append(f"<p>{diffed_text}</p>")
            else:
                for b in old_blocks[i1:i2]:
                    if b.type == "p": out.append(f'<p class="removed">{html.escape(b.content)}</p>')
                    else: out.append(f'<div class="removed-table">{b.content}</div>')
                for b in new_blocks[j1:j2]:
                    if b.type == "p": out.append(f'<p class="added">{html.escape(b.content)}</p>')
                    else: out.append(f'<div class="added-table">{b.content}</div>')
        return "".join(out)

    @staticmethod
    def pair_clauses(old_clauses: list[Clause], new_clauses: list[Clause]) -> list[ComparisonRow]:
        old_texts = [DiffEngine.get_plain_text(c.blocks) for c in old_clauses]
        new_texts = [DiffEngine.get_plain_text(c.blocks) for c in new_clauses]
        
        #vector embeddings
        all_texts = old_texts + new_texts
        if not all_texts:
            return []
            
        vectorizer = TfidfVectorizer(stop_words='english')
        vectorizer.fit(all_texts)
        old_vecs = vectorizer.transform(old_texts)
        new_vecs = vectorizer.transform(new_texts)
        sim_matrix = cosine_similarity(old_vecs, new_vecs) * 100

        old_matched = set()
        new_matched = set()
        pairs = []

        new_by_key = {c.key: (i, c) for i, c in enumerate(new_clauses)}
        for o_idx, old_c in enumerate(old_clauses):
            if old_c.key in new_by_key:
                n_idx, new_c = new_by_key[old_c.key]
                sim_score = sim_matrix[o_idx][n_idx]
                
                if sim_score >= 90.0:
                    status = "UNCHANGED"
                elif sim_score >= 65.0:
                    status = "CHANGED"
                else:
                    continue 
                    
                pairs.append((old_c, new_c, sim_score, status))
                old_matched.add(o_idx)
                new_matched.add(n_idx)

        for o_idx, old_c in enumerate(old_clauses):
            if o_idx in old_matched: continue
            
            best_match_idx = -1
            best_sim = -1.0
            
            for n_idx, new_c in enumerate(new_clauses):
                if n_idx in new_matched: continue
                sim = sim_matrix[o_idx][n_idx]
                
                if sim > best_sim:
                    best_sim = sim
                    best_match_idx = n_idx
                    
            if best_sim >= 65.0:
                status = "UNCHANGED" if best_sim >= 90.0 else "CHANGED"
                pairs.append((old_c, new_clauses[best_match_idx], best_sim, status))
                old_matched.add(o_idx)
                new_matched.add(best_match_idx)

        rows = []
        for (old_c, new_c, sim_score, status) in pairs:
            rows.append(ComparisonRow(
                index=0,
                old_heading=old_c.heading,
                new_heading=new_c.heading, 
                old_html=DiffEngine.render_blocks(old_c.blocks),
                new_html=DiffEngine.render_blocks(new_c.blocks),
                diff_html=DiffEngine.diff_blocks(old_c.blocks, new_c.blocks) if status == "CHANGED" else "",
                status=status,
                similarity=sim_score
            ))
            
        for o_idx, old_c in enumerate(old_clauses):
            if o_idx not in old_matched:
                rows.append(ComparisonRow(
                    index=0, old_heading=old_c.heading, new_heading="",
                    old_html=DiffEngine.render_blocks(old_c.blocks), new_html="", diff_html="",
                    status="REMOVED", similarity=0.0
                ))
                
        for n_idx, new_c in enumerate(new_clauses):
            if n_idx not in new_matched:
                rows.append(ComparisonRow(
                    index=0, old_heading="", new_heading=new_c.heading,
                    old_html="", new_html=DiffEngine.render_blocks(new_c.blocks), diff_html="",
                    status="ADDED", similarity=0.0
                ))
                
        rows.sort(key=lambda r: r.new_heading if r.new_heading else r.old_heading)
        for idx, r in enumerate(rows):
            r.index = idx + 1
            
        return rows