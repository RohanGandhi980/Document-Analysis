import pdfplumber
import difflib
import html
import re
import io
from dataclasses import dataclass

@dataclass
class Clause:
    heading: str
    key: str
    content_html: str

@dataclass
class ComparisonRow:
    index: int
    old_heading: str
    new_heading: str
    old_html: str
    new_html: str
    status: str
    similarity: float  #similarity score between two documents

class DynamicDocumentParser:
    
    CODE_RE = re.compile(r"^((?:AMC\d*\s*|GM\d*\s*|CAR\s*)?145\s*\.?\s*[A-Z]?\.\d+[A-Z]?(?:\s*\([a-z0-9]+\))*)(?:\s+|$|-)", re.IGNORECASE)

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
        clauses_dict[current_key] = {"heading": current_heading, "content": []}
        
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                width = page.width
                height = page.height
                bounding_box = (0, height * 0.1, width, height * 0.9)
                cropped_page = page.crop(bounding_box)
                
                tables = cropped_page.find_tables()
                table_bboxes = [t.bbox for t in tables]
                
                #extracting the tables properly
                words = cropped_page.extract_words(keep_blank_chars=True)
                filtered_words = []
                for w in words:
                    in_table = any(x0 <= w['x0'] and top <= w['top'] and x1 >= w['x1'] and bottom >= w['bottom'] 
                                   for x0, top, x1, bottom in table_bboxes)
                    if not in_table:
                        filtered_words.append(w)
                
                lines = {}
                for w in filtered_words:
                    line_y = round(w['top'] / 2) * 2 
                    if line_y not in lines:
                        lines[line_y] = []
                    lines[line_y].append(w)
                
                text_blocks = []
                for y in sorted(lines.keys()):
                    line_text = " ".join([w['text'] for w in sorted(lines[y], key=lambda x: x['x0'])])
                    clean_text = line_text.strip()
                    if len(clean_text) > 3 and not re.match(r"\.{4,}", clean_text): # Kill TOC dots
                        text_blocks.append({"type": "text", "content": clean_text, "y0": y})
                        
                for t in tables:
                    html_table = '<table class="doc-table">'
                    for row in t.extract():
                        html_table += "<tr>"
                        for cell in row:
                            cell_text = str(cell).replace("\n", " ") if cell is not None else ""
                            html_table += f"<td>{html.escape(cell_text)}</td>"
                        html_table += "</tr>"
                    html_table += "</table>"
                    text_blocks.append({"type": "table", "content": html_table, "y0": t.bbox[1]})
                
                text_blocks = sorted(text_blocks, key=lambda x: x["y0"])
                
                for item in text_blocks:
                    if item["type"] == "text":
                        if DynamicDocumentParser.CODE_RE.search(item["content"]):
                            current_heading = item["content"]
                            current_key = DynamicDocumentParser.get_clause_key(current_heading)
                            if current_key not in clauses_dict:
                                clauses_dict[current_key] = {"heading": current_heading, "content": []}
                            continue
                            
                        clauses_dict[current_key]["content"].append(html.escape(item["content"]))
                    else:
                        clauses_dict[current_key]["content"].append(item["content"])

        final_clauses = []
        for key, data in clauses_dict.items():
            if data["content"]:
                final_clauses.append(Clause(
                    heading=data["heading"],
                    key=key,
                    content_html="<br><br>".join(data["content"])
                ))
                
        return final_clauses

class DiffEngine:
    @staticmethod
    def get_similarity(old_text: str, new_text: str) -> float:
        """Computes similarity percentage between two strings."""
        if not old_text and not new_text: return 100.0
        if not old_text or not new_text: return 0.0
        # Strip HTML tags for accurate text similarity
        clean_old = re.sub(r'<[^>]+>', '', old_text)
        clean_new = re.sub(r'<[^>]+>', '', new_text)
        return difflib.SequenceMatcher(None, clean_old, clean_new).ratio() * 100

    @staticmethod
    def diff_html_safe(old_text: str, new_text: str) -> str:
        old_tokens = re.findall(r"<[^>]+>|[\w]+|[^\w<>]", old_text)
        new_tokens = re.findall(r"<[^>]+>|[\w]+|[^\w<>]", new_text)
        
        matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
        parts = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                parts.append("".join(new_tokens[j1:j2]))
            elif tag == "delete":
                for t in old_tokens[i1:i2]:
                    if t.startswith("<") and t.endswith(">"): parts.append(t)
                    else: parts.append(f'<span class="removed">{t}</span>')
            elif tag == "insert":
                for t in new_tokens[j1:j2]:
                    if t.startswith("<") and t.endswith(">"): parts.append(t)
                    else: parts.append(f'<span class="added">{t}</span>')
            elif tag == "replace":
                for t in old_tokens[i1:i2]:
                    if t.startswith("<") and t.endswith(">"): parts.append(t)
                    else: parts.append(f'<span class="removed">{t}</span>')
                for t in new_tokens[j1:j2]:
                    if t.startswith("<") and t.endswith(">"): parts.append(t)
                    else: parts.append(f'<span class="added">{t}</span>')
                        
        return "".join(parts)

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
            
            old_html = old_c.content_html if old_c else ""
            new_html = new_c.content_html if new_c else ""
            old_head = old_c.heading if old_c else ""
            new_head = new_c.heading if new_c else ""
            
            sim_score = DiffEngine.get_similarity(old_html, new_html)
            
            if old_c and not new_c: status = "REMOVED"
            elif new_c and not old_c: status = "ADDED"
            elif sim_score == 100.0: status = "UNCHANGED"
            else: status = "CHANGED"
            
            rows.append(ComparisonRow(
                index=idx + 1,
                old_heading=old_head,
                new_heading=new_head,
                old_html=old_html,
                new_html=new_html,
                status=status,
                similarity=sim_score
            ))
            
        return rows