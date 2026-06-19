import tempfile
import html
from pathlib import Path
import pandas as pd
import streamlit as st

#importing the logic we will use
from main import (
    ComparisonRow, 
    extract_clauses, 
    pair_clauses, 
    diff_html, 
    final_version_html
)

OLD_DEFAULT = Path(r"C:\Users\kbs930231\Downloads\CAR 145_1.pdf")
NEW_DEFAULT = Path(r"C:\Users\kbs930231\Downloads\CAR 145_2.pdf")

def save_uploaded(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        return tmp.name

def load_pdf_paths() -> tuple[str, str]:
    with st.sidebar:
        st.markdown('<div class="sidebar-title">DGCA Admin</div>', unsafe_allow_html=True)
        st.markdown('<div class="side-sep"></div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="nav-item"> <span>Dashboard Overview</span></div>
            <div class="nav-item"> <span>User Management</span></div>
            <div class="nav-item"> <span>Website Monitoring</span></div>
            <div class="nav-item active"> <span>Document Comparison</span></div>
            <div class="nav-item"> <span>Impact Analysis</span></div>
            <div class="nav-item"> <span>SLA Tracking</span></div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
        st.caption("PDF Sources")
        old_upload = st.file_uploader("Previous PDF", type=["pdf"])
        new_upload = st.file_uploader("Current PDF", type=["pdf"])
        st.markdown(
            """
            <div class="user-card">
            <div class="avatar">👤</div>
            <strong>srk.ade766@gmail.com</strong>
            <span>Administrator</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    old_path = save_uploaded(old_upload) if old_upload else str(OLD_DEFAULT)
    new_path = save_uploaded(new_upload) if new_upload else str(NEW_DEFAULT)
    return old_path, new_path

def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --dgca-blue: #073f88;
            --dgca-blue-2: #0a4d9f;
            --page-bg: #f3f4f6;
            --line: #d9dee6;
            --red: #f0442b;
            --green: #008f35;
        }
        .stApp { background: var(--page-bg); }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #073f88 0%, #06387a 100%);
            min-width: 310px !important;
        }
        [data-testid="stSidebar"] * { color: #fff; }
        [data-testid="stSidebar"] .stFileUploader label { color: #d7e8ff !important; }
        [data-testid="stSidebar"] .stFileUploader section { border-color: rgba(255,255,255,.25); }
        .sidebar-title {
            font-size: 28px;
            font-weight: 800;
            padding: 16px 0 12px;
        }
        .side-sep { height: 1px; background: rgba(255,255,255,.25); margin: 4px 0 20px; }
        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 13px 18px;
            border-radius: 4px;
            margin: 4px 0;
            font-size: 16px;
            font-weight: 600;
        }
        .nav-item.active { background: rgba(255,255,255,.13); box-shadow: inset 4px 0 0 #2d9cff; }
        .sidebar-spacer { height: 190px; border-bottom: 1px solid rgba(255,255,255,.25); }
        .user-card { text-align: center; padding: 18px 0 6px; color: #dbeafe; }
        .user-card .avatar { font-size: 30px; margin-bottom: 8px; }
        .user-card span { display: block; font-size: 13px; opacity: .85; margin-top: 2px; }
        .main .block-container {
            padding-top: 0;
            max-width: 1280px;
        }
        .topbar {
            background: #fff;
            margin: 0 -3rem 22px;
            padding: 22px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 2px 8px rgba(0,0,0,.12);
            border-bottom: 1px solid #e6e8ec;
        }
        .topbar h1 { margin: 0; font-size: 30px; color: #181d27; }
        .top-actions { display: flex; gap: 22px; align-items: center; }
        .bell {
            border: 1px solid #e1e5eb;
            width: 43px;
            height: 43px;
            display: grid;
            place-items: center;
            border-radius: 4px;
            color: #f2ae00;
            background: #fff;
        }
        .logout {
            border: 1px solid #053a7d;
            color: #053a7d;
            font-weight: 800;
            border-radius: 4px;
            padding: 11px 24px;
            background: #fff;
        }
        .tab-label {
            display: inline-block;
            margin-left: 80px;
            color: #1683e8;
            border: 1px solid #c9d7ea;
            border-bottom: 0;
            padding: 13px 18px;
            border-radius: 6px 6px 0 0;
            background: #fff;
        }
        .rule { border-top: 1px solid #d2d8e0; margin: 0 80px 24px; }
        .control-panel {
            background: #fff;
            border: 1px solid var(--line);
            border-radius: 4px;
            box-shadow: 0 1px 6px rgba(0,0,0,.13);
            padding: 18px;
            margin: 0 80px 34px;
        }
        .stButton > button {
            width: 100%;
            height: 44px;
            background: #003d8f;
            color: #fff;
            border: 0;
            border-radius: 4px;
            font-weight: 700;
        }
        .stButton > button:hover {
            background: #06377b;
            color: #fff;
            border: 0;
        }
        .empty-state {
            background: #fff;
            border: 1px solid #e1e5eb;
            border-radius: 4px;
            min-height: 150px;
            display: grid;
            place-items: center;
            color: #64748b;
            margin: 0 80px;
            box-shadow: 0 1px 4px rgba(0,0,0,.06);
        }
        .summary-strip {
            margin: 0 80px 16px;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }
        .metric-box {
            background: #fff;
            border: 1px solid var(--line);
            border-radius: 4px;
            padding: 14px 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,.06);
        }
        .metric-box strong { display: block; font-size: 24px; color: #132033; }
        .metric-box span { color: #64748b; font-size: 13px; }
        .result-card {
            background: #fff;
            border: 1px solid #d7dce3;
            border-radius: 4px;
            margin: 16px 80px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,.08);
        }
        .result-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 18px;
            border-bottom: 1px solid #d7dce3;
            font-weight: 800;
            color: #1f2937;
        }
        .badge {
            color: #fff;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 800;
        }
        .badge.Changed, .badge.Removed { background: #f04b23; }
        .badge.Added { background: #0c9e45; }
        .badge.Unchanged { background: #475569; }
        .result-body {
            margin: 18px;
            background: #fff;
            border: 1px solid #edf0f4;
            border-radius: 4px;
            padding: 14px;
            line-height: 1.7;
            font-size: 16px;
            color: #1f2937;
        }
        .removed { color: var(--red); text-decoration: line-through; }
        .added { color: var(--green); }
        .final-version {
            margin: 0 18px 18px;
            border-left: 3px solid #29c6e8;
            background: #eefdff;
            padding: 14px 16px;
            line-height: 1.55;
        }
        .removed-card {
            border-color: #ff6b61;
            background: #fff5f3;
        }
        .removed-card .result-head {
            color: #e13c2f;
            background: #fff1ef;
            border-bottom-color: #ff6b61;
        }
        .added-card {
            border-color: #57c783;
            background: #f5fff8;
        }
        .added-card .result-head {
            color: #087d35;
            background: #effcf4;
            border-bottom-color: #57c783;
        }
        @media (max-width: 900px) {
            .topbar, .control-panel, .empty-state, .result-card, .summary-strip {
                margin-left: 0;
                margin-right: 0;
            }
            .tab-label { margin-left: 0; }
            .rule { margin-left: 0; margin-right: 0; }
            .summary-strip { grid-template-columns: 1fr 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def render_result(row: ComparisonRow) -> None:
    heading = row.new_heading or row.old_heading
    if row.old_heading and row.new_heading and row.old_heading != row.new_heading:
        heading = f"{row.old_heading} // {row.new_heading}"
    
    classes = ["result-card"]
    if row.status == "Removed":
        classes.append("removed-card")
    if row.status == "Added":
        classes.append("added-card")

    if row.status == "Removed":
        body = f'<span class="removed">{html.escape(row.old_text).replace(chr(10), "<br>")}</span>'
        final = ""
    elif row.status == "Added":
        body = f'<span class="added">{html.escape(row.new_text).replace(chr(10), "<br>")}</span>'
        final = f'<div class="final-version">{final_version_html(row.new_text)}</div>'
    else:
        body = diff_html(row.old_text, row.new_text)
        final = f'<div class="final-version">{final_version_html(row.new_text)}</div>'

    st.markdown(
        f"""
        <div class="{' '.join(classes)}">
        <div class="result-head">
        <span>{row.index}. {html.escape(heading)}</span>
        <span class="badge {row.status}">{row.status}</span>
        </div>
        <div class="result-body">{body}</div>
            {final}
        </div>
        """,
        unsafe_allow_html=True,
    )

def main() -> None:
    st.set_page_config(page_title="Document Comparison", layout="wide")
    inject_css()
    old_path, new_path = load_pdf_paths()

    st.markdown(
        """
        <div class="topbar">
        <h1>CAR Document Comparison</h1>
        <div class="top-actions">
        <div class="bell"></div>
        <div class="logout">LOGOUT</div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not Path(old_path).exists() or not Path(new_path).exists():
        st.error("One or both PDF files were not found. Upload it again.")
        return

    with st.spinner("Reading CAR clauses from the PDFs"):
        old_clauses = extract_clauses(old_path)
        new_clauses = extract_clauses(new_path)
        rows = pair_clauses(old_clauses, new_clauses)

    st.markdown('<div class="tab-label">Range-Based Semantic Diff</div>', unsafe_allow_html=True)
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="control-panel">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            from_index = st.number_input(
                "From CAR Clause Index",
                min_value=1,
                max_value=max(len(rows), 1),
                value=1,
                step=1,
            )
        with col2:
            to_index = st.number_input(
                "To CAR Clause Index",
                min_value=1,
                max_value=max(len(rows), 1),
                value=min(50, max(len(rows), 1)),
                step=1,
            )
        with col3:
            st.write("")
            st.write("")
            compare = st.button("Compare Range", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("View CAR clause index", expanded=False):
        table = pd.DataFrame(
            [
                {
                    "Index": row.index,
                    "Previous Clause": row.old_heading,
                    "Current Clause": row.new_heading,
                    "Status": row.status,
                }
                for row in rows
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)

    if not compare:
        st.markdown(
            '<div class="empty-state">Enter From CAR Clause and TO CAR Clause, then click Compare Range to see comparison.</div>',
            unsafe_allow_html=True,
        )
        return

    start = min(from_index, to_index)
    end = max(from_index, to_index)
    selected = [row for row in rows if start <= row.index <= end]

    counts = {status: sum(1 for row in selected if row.status == status) for status in ["Changed", "Added", "Removed", "Unchanged"]}

    st.markdown(
        f"""
        <div class="summary-strip">
        <div class="metric-box"><strong>{len(selected)}</strong><span>Clauses compared</span></div>
        <div class="metric-box"><strong>{counts['Changed']}</strong><span>Changed</span></div>
        <div class="metric-box"><strong>{counts['Added']}</strong><span>Added</span></div>
        <div class="metric-box"><strong>{counts['Removed']}</strong><span>Removed</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for row in selected:
        render_result(row)

if __name__ == "__main__":
    main()