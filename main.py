import fitz  
import hashlib
import difflib
import html
import re
from collections import defaultdict
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
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


app = FastAPI(title="Dynamic Page-Wise Document Comparator")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dynamic Document Comparator</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f8f9fa; color: #1e293b; margin: 0; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { background: #fff; padding: 20px 30px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center;}
        .upload-form { display: flex; gap: 15px; align-items: center; }
        .file-input { border: 1px solid #cbd5e1; padding: 6px; border-radius: 4px; }
        .btn { background-color: #073f88; color: white; border: none; padding: 10px 20px; font-size: 14px; font-weight: bold; border-radius: 4px; cursor: pointer; }
        .btn:hover { background-color: #052c65; }
        
        /* Page Sections */
        .page-container { margin-bottom: 40px; background: white; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .page-header { background-color: #073f88; color: white; padding: 12px 20px; font-size: 18px; font-weight: bold; }
        
        /* Inner Diff Tables */
        .diff-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .diff-table th { background-color: #f1f5f9; color: #475569; font-size: 13px; text-transform: uppercase; padding: 10px 16px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        .diff-table td { padding: 16px; border-bottom: 1px solid #e2e8f0; vertical-align: top; font-size: 14px; line-height: 1.6; word-wrap: break-word;}
        .diff-table tr:hover { background-color: #f8fafc; }
        
        .col-status { width: 12%; }
        .col-prev { width: 44%; border-right: 1px solid #f1f5f9; }
        .col-curr { width: 44%; }

        /* Badges */
        .badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; color: white; letter-spacing: 0.5px;}
        .badge-UNCHANGED { background: #64748b; }
        .badge-CHANGED { background: #f04b23; }
        .badge-ADDED { background: #0c9e45; }
        .badge-REMOVED { background: #dc2626; }

        /* Inline Diff Colors */
        .inline-removed { color: #dc2626; text-decoration: line-through; background-color: #fee2e2; padding: 0 2px; border-radius: 2px; }
        .inline-added { color: #16a34a; background-color: #dcfce7; font-weight: bold; padding: 0 2px; border-radius: 2px; }
        
        /* Preserved PDF Tables */
        .pdf-table { width: 100%; border-collapse: collapse; margin-top: 5px; font-size: 13px; }
        .pdf-table th, .pdf-table td { border: 1px solid #cbd5e1; padding: 6px; text-align: left; background-color: #f8fafc;}
        
        .empty-cell { color: #94a3b8; font-style: italic; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h2 style="margin:0; color:#073f88;">Dynamic Document Comparison</h2>
                <p style="margin:4px 0 0 0; font-size: 14px; color:#64748b;">Page-by-Page Tabular Analysis</p>
            </div>
            <form action="/compare" method="post" enctype="multipart/form-data" class="upload-form">
                <div>
                    <span style="font-size:13px; font-weight:bold; margin-right:5px;">Previous:</span>
                    <input type="file" name="old_file" class="file-input" accept=".pdf" required>
                </div>
                <div>
                    <span style="font-size:13px; font-weight:bold; margin-right:5px; margin-left:10px;">Current:</span>
                    <input type="file" name="new_file" class="file-input" accept=".pdf" required>
                </div>
                <button type="submit" class="btn">Execute Comparison</button>
            </form>
        </div>
        
        <div id="results">
            {RESULTS}
        </div>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    empty_state = """
    <div style="text-align:center; padding: 80px; background: white; border-radius: 8px; border: 1px solid #e2e8f0; color:#64748b;">
        Upload two PDF documents above to generate the page-by-page comparison.
    </div>
    """
    return HTML_TEMPLATE.replace("{RESULTS}", empty_state)

@app.post("/compare", response_class=HTMLResponse)
async def compare_docs(old_file: UploadFile = File(...), new_file: UploadFile = File(...)):
    if not (old_file.filename.endswith('.pdf') and new_file.filename.endswith('.pdf')):
        raise HTTPException(status_code=400, detail="Both files must be PDFs.")
        
    old_bytes = await old_file.read()
    new_bytes = await new_file.read()
    
    old_blocks = DynamicDocumentParser.extract_blocks(old_bytes)
    new_blocks = DynamicDocumentParser.extract_blocks(new_bytes)
    
    comparison_results = DiffEngine.compare_documents(old_blocks, new_blocks)
    
    #grouping results by page number
    page_groups = defaultdict(list)
    for res in comparison_results:
        page_groups[res["page_num"]].append(res)
    
    html_output = []

    for page_num in sorted(page_groups.keys()):
        page_html = f"""
        <div class="page-container">
            <div class="page-header">Page {page_num}</div>
            <table class="diff-table">
                <thead>
                    <tr>
                        <th class="col-status">Status</th>
                        <th class="col-prev">Previous Document Content</th>
                        <th class="col-curr">Current Document Content</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for res in page_groups[page_num]:
            status = res["status"]
            old_html = res["old_html"] if res["old_html"] else '<span class="empty-cell">-- No Content --</span>'
            new_html = res["new_html"] if res["new_html"] else '<span class="empty-cell">-- No Content --</span>'
            
            if status == "REMOVED" and old_html != '<span class="empty-cell">-- No Content --</span>':
                 old_html = f'<div style="color: #dc2626; text-decoration: line-through;">{old_html}</div>'
            elif status == "ADDED" and new_html != '<span class="empty-cell">-- No Content --</span>':
                 new_html = f'<div style="color: #16a34a; font-weight: bold;">{new_html}</div>'

            page_html += f"""
                <tr>
                    <td class="col-status"><span class="badge badge-{status}">{status}</span></td>
                    <td class="col-prev">{old_html}</td>
                    <td class="col-curr">{new_html}</td>
                </tr>
            """
            
        page_html += """
                </tbody>
            </table>
        </div>
        """
        html_output.append(page_html)
        
    final_html = "\n".join(html_output)
    return HTML_TEMPLATE.replace("{RESULTS}", final_html)