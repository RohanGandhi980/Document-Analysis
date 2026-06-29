import fitz  # PyMuPDF
import hashlib
import difflib
import html
import re
from dataclasses import dataclass

CAR_HEADING_RE = re.compile(
    r"^(?:(?:AMC|GM|CAR)\s*\d*\s*(?:No\.?\s*\d+\s*)?(?:TO\s+)?)*"
    r"(?:CAR-?\s*)?145\s*\.?\s*(?:[A-Z]\s*\.?\s*)?\d+[A-Z]?"
    r"(?:\s*\([a-z0-9]+\))*",
    re.IGNORECASE,
)
GENERIC_HEADING_RE = re.compile(r"^(?:Section|Article|Part|Chapter)\s+\d+|^\d+\.\d+", re.IGNORECASE)
NOISE_HEADING_RE = re.compile(
    r"^(?:CAR\s*145\b|Issue\s+\d|Page\s+\d|\d+\s*\|\s*P\s*a\s*g\s*e|"
    r"FOREWORD|RECORD OF REVISIONS|CONTENTS|TABLE OF CONTENTS|SECTION\b)",
    re.IGNORECASE,
)

@dataclass
class DocBlock:
    type: str     
    content: str    
    hash_val: str   
    group_key: str  

class DynamicDocumentParser:
    @staticmethod
    def get_md5(text: str) -> str:
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    @staticmethod
    def is_heading(text: str, is_bold: bool, font_size: float) -> bool:
        """Determines if a text block is a structural clause heading."""
        if len(text) > 150 or len(text) < 3:
            return False
        if NOISE_HEADING_RE.match(text):
            return False
            
        if CAR_HEADING_RE.match(text):
            return True
            
        if (GENERIC_HEADING_RE.match(text) or is_bold) and font_size >= 10:
            if len(text.split()) < 15: 
                return True
                
        return False

    @staticmethod
    def extract_blocks(file_bytes: bytes) -> list[DocBlock]:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        blocks = []
        seen_hashes = set()

        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            
            tables = page.find_tables()
            table_items = []
            table_rects = []
            
            for tab in tables:
                rect = fitz.Rect(tab.bbox)
                table_rects.append(rect)
                
                html_table = '<table class="pdf-table">'
                for row in tab.extract():
                    html_table += "<tr>"
                    for cell in row:
                        cell_text = str(cell).replace("\n", " ") if cell is not None else ""
                        html_table += f"<td>{html.escape(cell_text)}</td>"
                    html_table += "</tr>"
                html_table += "</table>"
                
                table_items.append({"type": "table", "content": html_table, "y0": rect.y0})

            text_items = []
            page_dict = page.get_text("dict", sort=True)
            for b in page_dict.get("blocks", []):
                if b.get("type") == 0:
                    rect = fitz.Rect(b["bbox"])
                    
                    if any(rect.intersects(tr) for tr in table_rects):
                        continue
                    
                    text = ""
                    is_bold = False
                    max_font_size = 0
                    
                    for line in b.get("lines", []):
                        for span in line.get("spans", []):
                            text += span.get("text", "") + " "
                            if bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower():
                                is_bold = True
                            if span.get("size", 0) > max_font_size:
                                max_font_size = span.get("size", 0)
                    
                    text = re.sub(r'[ \t]+', ' ', text).strip()
                    if len(text) > 5: 
                        text_items.append({
                            "type": "text", "content": text, "y0": rect.y0, 
                            "is_bold": is_bold, "font_size": max_font_size
                        })
            all_items = sorted(table_items + text_items, key=lambda x: x["y0"])

            current_group = f"Page {page_number}"
            
            for item in all_items:
                if item["type"] == "text":
                    if DynamicDocumentParser.is_heading(item["content"], item["is_bold"], item["font_size"]):
                        current_group = item["content"] 
                
                h = DynamicDocumentParser.get_md5(item["content"])
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    blocks.append(DocBlock(
                        type=item["type"], 
                        content=item["content"], 
                        hash_val=h, 
                        group_key=current_group
                    ))
                            
        return blocks

class DiffEngine:
    @staticmethod
    def word_level_diff(old_text: str, new_text: str) -> str:
        old_tokens = re.split(r'(\s+)', old_text)
        new_tokens = re.split(r'(\s+)', new_text)
        matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
        parts = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                parts.append(html.escape("".join(new_tokens[j1:j2])))
            elif tag == "delete":
                parts.append(f'<span class="inline-removed">{html.escape("".join(old_tokens[i1:i2]))}</span>')
            elif tag == "insert":
                parts.append(f'<span class="inline-added">{html.escape("".join(new_tokens[j1:j2]))}</span>')
            elif tag == "replace":
                parts.append(f'<span class="inline-removed">{html.escape("".join(old_tokens[i1:i2]))}</span>')
                parts.append(f'<span class="inline-added">{html.escape("".join(new_tokens[j1:j2]))}</span>')
                
        return "".join(parts).replace("\n", "<br>")

    @staticmethod
    def compare_documents(old_blocks: list[DocBlock], new_blocks: list[DocBlock]) -> list[dict]:
        matcher = difflib.SequenceMatcher(
            None, 
            [b.content for b in old_blocks], 
            [b.content for b in new_blocks], 
            autojunk=False
        )
        
        results = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    nb = new_blocks[j1+k]
                    results.append({"status": "UNCHANGED", "old_html": old_blocks[i1+k].content, "new_html": nb.content, "group_key": nb.group_key})
            
            elif tag == "replace":
                if (i2 - i1) == (j2 - j1):
                    for k in range(i2 - i1):
                        ob = old_blocks[i1+k]
                        nb = new_blocks[j1+k]
                        if ob.type == 'text' and nb.type == 'text':
                            diffed_html = DiffEngine.word_level_diff(ob.content, nb.content)
                            results.append({"status": "CHANGED", "old_html": ob.content, "new_html": diffed_html, "group_key": nb.group_key})
                        else:
                            results.append({"status": "REMOVED", "old_html": ob.content, "new_html": "", "group_key": ob.group_key})
                            results.append({"status": "ADDED", "old_html": "", "new_html": nb.content, "group_key": nb.group_key})
                else:
                    for i in range(i1, i2):
                        results.append({"status": "REMOVED", "old_html": old_blocks[i].content, "new_html": "", "group_key": old_blocks[i].group_key})
                    for j in range(j1, j2):
                        results.append({"status": "ADDED", "old_html": "", "new_html": new_blocks[j].content, "group_key": new_blocks[j].group_key})
            
            elif tag == "delete":
                for i in range(i1, i2):
                    results.append({"status": "REMOVED", "old_html": old_blocks[i].content, "new_html": "", "group_key": old_blocks[i].group_key})
            
            elif tag == "insert":
                for j in range(j1, j2):
                    results.append({"status": "ADDED", "old_html": "", "new_html": new_blocks[j].content, "group_key": new_blocks[j].group_key})
                    
        return results