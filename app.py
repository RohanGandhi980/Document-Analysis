from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
import html
from nlp_engine import DynamicDocumentParser, DiffEngine

app = FastAPI(title="Clause-Wise Document Comparator")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title> Document Comparison</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f3f4f6; color: #1e293b; margin: 0; }
        
        .topbar { background: #fff; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 4px rgba(0,0,0,0.1); margin-bottom: 30px; }
        .topbar h1 { margin: 0; font-size: 24px; color: #181d27; }
        .top-actions { display: flex; gap: 15px; align-items: center; }
        .logout { border: 1px solid #053a7d; color: #053a7d; font-weight: 700; border-radius: 4px; padding: 10px 20px; font-size:13px; text-transform:uppercase; cursor:pointer;}
        
        .container { max-width: 1300px; margin: 0 auto; padding: 0 20px;}
        
        .upload-card { background: white; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #e2e8f0; margin-bottom: 30px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .file-input { margin: 10px; }
        .btn { background-color: #073f88; color: white; border: none; padding: 10px 24px; font-size: 15px; font-weight: bold; border-radius: 4px; cursor: pointer; }
        
        .result-card { background: #fff; border: 1px solid #d7dce3; border-radius: 6px; margin-bottom: 25px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
        .result-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid #d7dce3; font-weight: 800; color: #1f2937; background-color: #f8fafc;}
        .result-body { padding: 18px; line-height: 1.7; font-size: 15px; color: #1f2937; }
        
        .CHANGED-card { border-color: #d7dce3; }
        .REMOVED-card { border-color: #ff6b61; background: #fff5f3; }
        .REMOVED-card .result-head { color: #e13c2f; background: #fff1ef; border-bottom-color: #ff6b61; }
        .ADDED-card { border-color: #57c783; background: #f5fff8; }
        .ADDED-card .result-head { color: #087d35; background: #effcf4; border-bottom-color: #57c783; }

        .head-right { display: flex; align-items: center; gap: 12px; }
        .sim-score { font-size: 12px; color: #64748b; font-weight: 600; }

        .badge { color: #fff; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 800; text-transform:uppercase; letter-spacing:0.5px;}
        .badge.CHANGED { background: #f04b23; }
        .badge.ADDED { background: #0c9e45; }
        .badge.REMOVED { background: #dc2626; }
        .badge.UNCHANGED { background: #64748b; }

        .removed { color: #dc2626; text-decoration: line-through; background-color: #fee2e2; padding: 0 2px; border-radius: 2px;}
        .added { color: #16a34a; font-weight: bold; background-color: #dcfce7; padding: 0 2px; border-radius: 2px;}

        .toggle-btn { margin: 0 18px 15px; background: #e0f2fe; color: #0284c7; border: 1px solid #bae6fd; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: bold; }
        .toggle-btn:hover { background: #bae6fd; }
        .final-version { display: none; margin: 0 18px 18px; border-left: 3px solid #29c6e8; background: #eefdff; padding: 14px 16px; line-height: 1.6; font-size: 14px;}
        
        .doc-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
        .doc-table th, .doc-table td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; background-color: #ffffff;}
    </style>
    <script>
        function toggleFinal(btn) {
            var finalDiv = btn.nextElementSibling;
            if (finalDiv.style.display === "block") {
                finalDiv.style.display = "none";
                btn.innerHTML = "View Final Version";
            } else {
                finalDiv.style.display = "block";
                btn.innerHTML = "Hide Final Version";
            }
        }
    </script>
</head>
<body>
    <div class="topbar">
        <h1>CAR Document Comparison</h1>
        <div class="top-actions">
            <div class="bell">🔔</div>
            <div class="logout">LOGOUT</div>
        </div>
    </div>

    <div class="container">
        <div class="upload-card">
            <form action="/compare" method="post" enctype="multipart/form-data">
                <strong style="font-size:14px; margin-right:5px;">Previous PDF:</strong> <input type="file" name="old_file" class="file-input" accept=".pdf" required>
                <strong style="font-size:14px; margin-left:15px; margin-right:5px;">Current PDF:</strong> <input type="file" name="new_file" class="file-input" accept=".pdf" required>
                <button type="submit" class="btn" style="margin-left: 15px;">Compare Clauses</button>
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
    empty_state = '<div style="text-align:center; padding: 60px; background: white; border-radius: 8px; border: 1px solid #e2e8f0; color:#64748b;">Upload 2 PDF to generate clause wise comparison.</div>'
    return HTML_TEMPLATE.replace("{RESULTS}", empty_state)

@app.post("/compare", response_class=HTMLResponse)
async def compare_docs(old_file: UploadFile = File(...), new_file: UploadFile = File(...)):
    if not (old_file.filename.endswith('.pdf') and new_file.filename.endswith('.pdf')):
        raise HTTPException(status_code=400, detail="Both files must be PDFs.")
        
    old_bytes = await old_file.read()
    new_bytes = await new_file.read()
    
    old_clauses = DynamicDocumentParser.extract_clauses(old_bytes)
    new_clauses = DynamicDocumentParser.extract_clauses(new_bytes)
    
    rows = DiffEngine.pair_clauses(old_clauses, new_clauses)
    
    html_output = []
    
    for row in rows:
        heading = row.new_heading or row.old_heading
        if row.old_heading and row.new_heading and row.old_heading != row.new_heading:
            heading = f"{row.old_heading} // {row.new_heading}"
            
        status = row.status
        sim_score_text = f"Similarity: {row.similarity:.1f}%" if status not in ["ADDED", "REMOVED"] else ""
        
        if status == "REMOVED":
            body_html = f'<span class="removed">{row.old_html}</span>'
            final_html = ""
        elif status == "ADDED":
            body_html = f'<span class="added">{row.new_html}</span>'
            final_html = row.new_html
        elif status == "UNCHANGED":
            body_html = row.old_html
            final_html = row.old_html
        else:
            body_html = DiffEngine.diff_html_safe(row.old_html, row.new_html)
            final_html = row.new_html
            
        card_html = f"""
        <div class="result-card {status}-card">
            <div class="result-head">
                <span>{html.escape(heading)}</span>
                <div class="head-right">
                    <span class="sim-score">{sim_score_text}</span>
                    <span class="badge {status}">{status}</span>
                </div>
            </div>
            <div class="result-body">
                {body_html}
            </div>
        """
        
        if status != "REMOVED" and status != "UNCHANGED":
            card_html += f"""
            <button class="toggle-btn" onclick="toggleFinal(this)">View Final Version</button>
            <div class="final-version">
                {final_html}
            </div>
            """
            
        card_html += "</div>"
        html_output.append(card_html)
        
    final_html = "\n".join(html_output)
    return HTML_TEMPLATE.replace("{RESULTS}", final_html)