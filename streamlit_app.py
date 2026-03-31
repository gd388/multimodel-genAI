import os
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="FinSight AI — Document Intelligence",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design system ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Global ─────────────────────────────────────────────────────────── */
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .block-container { padding: 2rem 2.5rem 3rem; max-width: 1200px; }
    header[data-testid="stHeader"] { background: transparent; }

    /* ── Sidebar ────────────────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        color: #e2e8f0;
    }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown li,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stCaption p {
        color: #94a3b8 !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #f1f5f9 !important;
    }
    section[data-testid="stSidebar"] hr { border-color: #334155; }
    section[data-testid="stSidebar"] .stRadio label span {
        color: #cbd5e1 !important;
    }
    section[data-testid="stSidebar"] .stButton > button {
        background: #334155; color: #e2e8f0; border: 1px solid #475569;
        border-radius: 8px; font-weight: 500; transition: all .2s;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: #475569; border-color: #64748b;
    }

    /* ── Cards ──────────────────────────────────────────────────────────── */
    .saas-card {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 24px; margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
        transition: box-shadow .2s;
    }
    .saas-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.08); }
    .saas-card h4 { margin: 0 0 4px; font-size: .85rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }

    /* ── Answer card ────────────────────────────────────────────────────── */
    .answer-card {
        background: linear-gradient(135deg, #f0f9ff, #eff6ff);
        border: 1px solid #bfdbfe; border-left: 4px solid #3b82f6;
        border-radius: 12px; padding: 24px 28px; margin: 20px 0;
    }
    .answer-card p { color: #1e293b; line-height: 1.7; font-size: .95rem; }

    /* ── Source badge ───────────────────────────────────────────────────── */
    .source-badge {
        display: inline-block; background: #f1f5f9; border: 1px solid #e2e8f0;
        border-radius: 6px; padding: 2px 10px; font-size: .75rem;
        font-weight: 500; color: #475569; margin-right: 6px;
    }
    .score-badge {
        display: inline-block; background: #ecfdf5; border: 1px solid #a7f3d0;
        border-radius: 6px; padding: 2px 10px; font-size: .75rem;
        font-weight: 600; color: #065f46;
    }

    /* ── Metric cards ──────────────────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 16px 20px;
    }
    div[data-testid="stMetric"] label { font-size: .78rem; color: #64748b; font-weight: 500; text-transform: uppercase; letter-spacing: .04em; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { font-size: 1.1rem; font-weight: 700; color: #0f172a; }

    /* ── Hero ───────────────────────────────────────────────────────────── */
    .hero-title {
        font-size: 1.75rem; font-weight: 700; color: #0f172a;
        margin-bottom: 4px; letter-spacing: -0.02em;
    }
    .hero-sub {
        font-size: .95rem; color: #64748b; margin-bottom: 24px;
    }
    .brand-dot { color: #3b82f6; }

    /* ── Pill nav ───────────────────────────────────────────────────────── */
    .pill-active {
        display: inline-block; background: #3b82f6; color: #fff;
        padding: 6px 18px; border-radius: 20px; font-size: .82rem;
        font-weight: 600; margin-right: 8px;
    }
    .pill-inactive {
        display: inline-block; background: #f1f5f9; color: #475569;
        padding: 6px 18px; border-radius: 20px; font-size: .82rem;
        font-weight: 500; margin-right: 8px; cursor: pointer;
        border: 1px solid #e2e8f0;
    }

    /* ── Primary button ─────────────────────────────────────────────────── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        color: #fff; border: none; border-radius: 8px;
        font-weight: 600; padding: 0.55em 1.5em;
        box-shadow: 0 2px 8px rgba(37,99,235,.25);
        transition: all .2s;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        box-shadow: 0 4px 14px rgba(37,99,235,.35);
    }

    /* ── Text area ──────────────────────────────────────────────────────── */
    .stTextArea textarea {
        border: 1.5px solid #e2e8f0; border-radius: 10px;
        font-size: .92rem; padding: 14px 16px;
        transition: border-color .2s;
    }
    .stTextArea textarea:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,.12); }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # Brand
    st.markdown("""
    <div style="padding: 8px 0 4px;">
        <span style="font-size: 1.35rem; font-weight: 700; color: #f1f5f9; letter-spacing: -0.03em;">
            <span style="color: #3b82f6;">◆</span> FinSight AI
        </span>
        <br>
        <span style="font-size: .78rem; color: #64748b;">Document Intelligence Platform</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    # Navigation
    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Navigation</p>', unsafe_allow_html=True)
    if st.button("📈  Dashboard", use_container_width=True):
        st.switch_page("pages/1_Dashboard.py")

    st.markdown("---")

    # Model selection
    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">AI Model</p>', unsafe_allow_html=True)
    model_choice = st.radio(
        "Model",
        options=["Groq  ·  LLaMA 3.3 70B", "Gemini  ·  2.0 Flash Lite"],
        index=0,
        label_visibility="collapsed",
        help="If the selected model fails, HuggingFace Mistral-7B is used as automatic fallback.",
    )
    mode = "groq" if "Groq" in model_choice else "gemini"

    st.markdown("---")

    # Search settings
    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Search Settings</p>', unsafe_allow_html=True)
    top_k = st.slider("Context chunks", min_value=1, max_value=10, value=5)
    filter_doc = st.text_input("Filter by document", placeholder="e.g. Apple 10-K")

    st.markdown("---")

    # Upload
    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Upload &amp; Ingest</p>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Choose a PDF", type=["pdf"], label_visibility="collapsed")
    if uploaded_file and st.button("Upload & Process", use_container_width=True):
        with st.spinner("Uploading…"):
            try:
                resp = requests.post(
                    f"{API_URL}/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                st.success(f"Queued — Job `{data['job_id'][:8]}…`")
            except Exception as e:
                st.error(f"Upload failed: {e}")

    st.markdown("---")

    # Remove data
    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Data Management</p>', unsafe_allow_html=True)
    if st.button("🗑  Remove All Data", use_container_width=True):
        with st.spinner("Removing…"):
            try:
                resp = requests.delete(f"{API_URL}/remove", timeout=30)
                resp.raise_for_status()
                st.success("All indexed data cleared.")
            except requests.ConnectionError:
                st.error("API is still starting up. Please wait a moment and try again.")
            except Exception as e:
                st.error(f"Failed: {e}")

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; padding: 4px 0;">
        <span style="font-size: .68rem; color: #475569;">
            Textract · fastembed · Qdrant<br>Groq · Gemini · HuggingFace
        </span>
    </div>
    """, unsafe_allow_html=True)


# ── Main content ──────────────────────────────────────────────────────────────
# Nav pills
st.markdown("""
<div style="margin-bottom: 16px;">
    <span class="pill-active">Query</span>
    <span class="pill-inactive">Dashboard</span>
</div>
""", unsafe_allow_html=True)

# Hero
st.markdown("""
<p class="hero-title">Ask your financial documents<span class="brand-dot">.</span></p>
<p class="hero-sub">Powered by RAG — retrieve precise answers from 10-Ks, earnings reports, and more.</p>
""", unsafe_allow_html=True)

# Active model indicator
_model_short = "Groq / LLaMA 3.3 70B" if mode == "groq" else "Gemini 2.0 Flash Lite"
st.markdown(f"""
<div style="display:flex;align-items:center;gap:8px;margin-bottom:18px;">
    <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;display:inline-block;"></span>
    <span style="font-size:.82rem;color:#64748b;">Active model: <strong style="color:#0f172a;">{_model_short}</strong> &nbsp;·&nbsp; top-{top_k} chunks &nbsp;·&nbsp; auto-fallback enabled</span>
</div>
""", unsafe_allow_html=True)

# Query input
question = st.text_area(
    "Your question",
    placeholder="What was Apple's total revenue in fiscal year 2023? How did gross margin change year-over-year?",
    height=100,
    label_visibility="collapsed",
)

col_ask, col_space = st.columns([1, 5])
with col_ask:
    ask = st.button("Ask FinSight", type="primary", use_container_width=True)


# ── Results ───────────────────────────────────────────────────────────────────
if ask:
    if not question.strip():
        st.warning("Please enter a question.")
    else:
        with st.spinner(f"Searching & generating via {_model_short}…"):
            try:
                payload = {
                    "question":   question,
                    "mode":       mode,
                    "top_k":      top_k,
                    "filter_doc": filter_doc or None,
                }
                resp = requests.post(f"{API_URL}/query", json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()

                # ── Answer ────────────────────────────────────────────────────
                st.markdown(f"""
                <div class="answer-card">
                    <h4 style="margin:0 0 10px;font-size:.8rem;color:#3b82f6;text-transform:uppercase;letter-spacing:.06em;font-weight:600;">Answer</h4>
                    <p style="margin:0;">{data["answer"]}</p>
                </div>
                """, unsafe_allow_html=True)

                # ── Provider info ─────────────────────────────────────────────
                c1, c2, c3 = st.columns(3)
                c1.metric("Provider", data["provider"].capitalize())
                c2.metric("Model", data["model"])
                c3.metric("Sources Used", len(data["sources"]))

                # ── Sources ───────────────────────────────────────────────────
                st.markdown("""
                <div style="margin-top:12px;">
                    <h4 style="font-size:.8rem;color:#64748b;text-transform:uppercase;letter-spacing:.06em;font-weight:600;">Retrieved Sources</h4>
                </div>
                """, unsafe_allow_html=True)

                for i, src in enumerate(data["sources"], 1):
                    title   = src.get("doc_title") or "Unknown"
                    section = src.get("section") or "—"
                    score   = src.get("score", 0)
                    with st.expander(f"Source {i}  ·  {title}  ·  {section}"):
                        st.markdown(f"""
                        <div style="display:flex;gap:6px;margin-bottom:10px;">
                            <span class="source-badge">{title}</span>
                            <span class="source-badge">{section}</span>
                            <span class="score-badge">Score: {score}</span>
                        </div>
                        """, unsafe_allow_html=True)
                        st.code(src.get("snippet", ""), language=None)

            except requests.HTTPError as e:
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                st.error(f"API error: {detail}")
            except Exception as e:
                st.error(f"Request failed: {e}")
