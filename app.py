from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
import html

from nlp_engine import DynamicDocumentParser, DiffEngine

app = FastAPI(title="Dynamic Clause-Wise Document Comparator")

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
        
        /* Clause/Page Sections */
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
                <h2 style="margin:0; color:#073f88;">Document Comparison</h2>
                <p style="margin:4px 0 0 0; font-size: 14px; color:#64748b;">Clause & Page-by-Page Tabular Analysis</p>
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
        Upload two PDF documents above to generate the clause-wise comparison.
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
    
    groups = {}
    group_keys = []
    for res in comparison_results:
        gk = res["group_key"]
        if gk not in groups:
            groups[gk] = []
            group_keys.append(gk)
        groups[gk].append(res)
    
    html_output = []
    
    for gk in group_keys:
        page_html = f"""
        <div class="page-container">
            <div class="page-header">{html.escape(gk)}</div>
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
        
        for res in groups[gk]:
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