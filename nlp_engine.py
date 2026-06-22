import fitz  # 
import hashlib
import difflib
import html
import re
from dataclasses import dataclass

@dataclass
class DocBlock:
    type: str       
    content: str    
    hash_val: str  
    page_num: int   

class DynamicDocumentParser:
    @staticmethod
    def get_md5(text: str) -> str:
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    @staticmethod
    def extract_blocks(file_bytes: bytes) -> list[DocBlock]:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        blocks = []
        seen_hashes = set()

        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            
            # Extract Tables
            tables = page.find_tables()
            table_rects = []
            
            for tab in tables:
                table_rects.append(fitz.Rect(tab.bbox))
                
                html_table = '<table class="pdf-table">'
                for row in tab.extract():
                    html_table += "<tr>"
                    for cell in row:
                        cell_text = str(cell).replace("\n", " ") if cell is not None else ""
                        html_table += f"<td>{html.escape(cell_text)}</td>"
                    html_table += "</tr>"
                html_table += "</table>"
                
                h = DynamicDocumentParser.get_md5(html_table)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    blocks.append(DocBlock(type="table", content=html_table, hash_val=h, page_num=page_number))

            # Extract Text Blocks
            page_dict = page.get_text("dict", sort=True)
            for b in page_dict.get("blocks", []):
                if b.get("type") == 0:
                    rect = fitz.Rect(b["bbox"])
                    
                    is_in_table = any(rect.intersects(tr) for tr in table_rects)
                    if is_in_table:
                        continue
                    
                    text = ""
                    for line in b.get("lines", []):
                        for span in line.get("spans", []):
                            text += span.get("text", "") + " "
                    
                    text = re.sub(r'[ \t]+', ' ', text).strip()
                    
                    if len(text) > 5: 
                        h = DynamicDocumentParser.get_md5(text)
                        if h not in seen_hashes: 
                            seen_hashes.add(h)
                            blocks.append(DocBlock(type="text", content=text, hash_val=h, page_num=page_number))
                            
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
                    results.append({"status": "UNCHANGED", "old_html": old_blocks[i1+k].content, "new_html": nb.content, "page_num": nb.page_num})
            
            elif tag == "replace":
                if (i2 - i1) == (j2 - j1):
                    for k in range(i2 - i1):
                        ob = old_blocks[i1+k]
                        nb = new_blocks[j1+k]
                        if ob.type == 'text' and nb.type == 'text':
                            diffed_html = DiffEngine.word_level_diff(ob.content, nb.content)
                            results.append({"status": "CHANGED", "old_html": ob.content, "new_html": diffed_html, "page_num": nb.page_num})
                        else:
                            results.append({"status": "REMOVED", "old_html": ob.content, "new_html": "", "page_num": ob.page_num})
                            results.append({"status": "ADDED", "old_html": "", "new_html": nb.content, "page_num": nb.page_num})
                else:
                    for i in range(i1, i2):
                        results.append({"status": "REMOVED", "old_html": old_blocks[i].content, "new_html": "", "page_num": old_blocks[i].page_num})
                    for j in range(j1, j2):
                        results.append({"status": "ADDED", "old_html": "", "new_html": new_blocks[j].content, "page_num": new_blocks[j].page_num})
            
            elif tag == "delete":
                for i in range(i1, i2):
                    results.append({"status": "REMOVED", "old_html": old_blocks[i].content, "new_html": "", "page_num": old_blocks[i].page_num})
            
            elif tag == "insert":
                for j in range(j1, j2):
                    results.append({"status": "ADDED", "old_html": "", "new_html": new_blocks[j].content, "page_num": new_blocks[j].page_num})
                    
        return results