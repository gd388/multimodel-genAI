import os
import re
import streamlit as st
import pandas as pd
from collections import defaultdict, Counter
from qdrant_client import QdrantClient

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION  = "documents"

st.set_page_config(page_title="FinSight AI — Dashboard", page_icon="◆", layout="wide")

# ── Design system (shared with main app) ──────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .block-container { padding: 2rem 2.5rem 3rem; max-width: 1200px; }
    header[data-testid="stHeader"] { background: transparent; }

    /* ── Sidebar ──────────────────────────────────────────────────────── */
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
    section[data-testid="stSidebar"] .stButton > button {
        background: #334155; color: #e2e8f0; border: 1px solid #475569;
        border-radius: 8px; font-weight: 500; transition: all .2s;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: #475569; border-color: #64748b;
    }

    /* ── KPI cards ────────────────────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,.04);
    }
    div[data-testid="stMetric"] label {
        font-size: .72rem; color: #64748b; font-weight: 600;
        text-transform: uppercase; letter-spacing: .06em;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-size: 1.25rem; font-weight: 700; color: #0f172a;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricDelta"] > div {
        font-size: .78rem; font-weight: 600;
    }

    /* ── Section cards ────────────────────────────────────────────────── */
    .dash-section {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 24px 28px; margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,.04);
    }
    .dash-section h3 {
        font-size: .95rem; font-weight: 700; color: #0f172a;
        margin: 0 0 4px; letter-spacing: -0.01em;
    }
    .dash-section .section-sub {
        font-size: .78rem; color: #94a3b8; margin: 0 0 16px;
    }

    /* ── Pill nav ─────────────────────────────────────────────────────── */
    .pill-active {
        display: inline-block; background: #3b82f6; color: #fff;
        padding: 6px 18px; border-radius: 20px; font-size: .82rem;
        font-weight: 600; margin-right: 8px;
    }
    .pill-inactive {
        display: inline-block; background: #f1f5f9; color: #475569;
        padding: 6px 18px; border-radius: 20px; font-size: .82rem;
        font-weight: 500; margin-right: 8px; border: 1px solid #e2e8f0;
    }

    /* ── Data table ───────────────────────────────────────────────────── */
    .stDataFrame { border-radius: 10px; overflow: hidden; }

    /* ── Hero ──────────────────────────────────────────────────────────── */
    .hero-title {
        font-size: 1.75rem; font-weight: 700; color: #0f172a;
        margin-bottom: 4px; letter-spacing: -0.02em;
    }
    .hero-sub { font-size: .95rem; color: #64748b; margin-bottom: 24px; }
    .brand-dot { color: #3b82f6; }

    /* ── Stats row ────────────────────────────────────────────────────── */
    .stat-row {
        display: flex; gap: 24px; margin-bottom: 24px; flex-wrap: wrap;
    }
    .stat-item {
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
        padding: 10px 20px; min-width: 120px;
    }
    .stat-item .stat-label { font-size: .68rem; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }
    .stat-item .stat-value { font-size: 1.05rem; color: #0f172a; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
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

    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Navigation</p>', unsafe_allow_html=True)
    if st.button("🔍  Query Documents", use_container_width=True):
        st.switch_page("streamlit_app.py")

    st.markdown("---")

    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Actions</p>', unsafe_allow_html=True)
    if st.button("↻  Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    st.markdown('<p style="font-size:.7rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Data Management</p>', unsafe_allow_html=True)
    _remove_all = st.button("🗑  Remove All Data", use_container_width=True)

    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; padding: 4px 0;">
        <span style="font-size: .68rem; color: #475569;">
            Textract · fastembed · Qdrant<br>Groq · Gemini · HuggingFace
        </span>
    </div>
    """, unsafe_allow_html=True)


API_URL = os.getenv("API_URL", "http://localhost:8000")


# ── Fetch all chunks ──────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def fetch_chunks():
    q = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    try:
        info = q.get_collection(COLLECTION)
        if info.points_count == 0:
            return []
    except Exception:
        return []
    pts, offset = [], None
    while True:
        result, offset = q.scroll(COLLECTION, limit=250, offset=offset,
                                  with_payload=True, with_vectors=False)
        pts.extend(result)
        if offset is None:
            break
    return [p.payload for p in pts if p.payload]


def _remove_all_data():
    """Call the API to clear all indexed data."""
    import requests
    try:
        resp = requests.delete(f"{API_URL}/remove", timeout=15)
        resp.raise_for_status()
        return True
    except Exception:
        return False


def _remove_document(doc_title: str):
    """Call the API to remove a specific document."""
    import requests
    try:
        resp = requests.delete(f"{API_URL}/remove/{doc_title}", timeout=15)
        resp.raise_for_status()
        return True
    except Exception:
        return False


# ── Parse markdown tables from chunks ─────────────────────────────────────────

# Line items we want to extract (label → display name)
METRICS = {
    "total net sales":           "Total Net Sales",
    "net income":                "Net Income",
    "gross margin":              "Gross Margin",
    "operating income":          "Operating Income",
    "research and development":  "R&D Expense",
    "total cost of sales":       "Cost of Sales",
    "total operating expenses":  "Operating Expenses",
    "earnings per share":        "Earnings Per Share",
    "dividends and dividend":    "Dividends Paid",
    "total assets":              "Total Assets",
    "total liabilities":         "Total Liabilities",
    "cash and cash equivalents": "Cash & Equivalents",
    "total long-lived assets":   "Long-Lived Assets",
}

_NUM_RE = re.compile(r'[\$\s]*\(?([\d,]+(?:\.\d+)?)\)?')


def _parse_number(s: str) -> float | None:
    """Parse a cell value like '$ 383,285' or '(3,068)' into a float."""
    s = s.strip()
    if not s or s == "—":
        return None
    neg = "(" in s
    m = _NUM_RE.search(s)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return -val if neg else val


def extract_financials(payloads: list[dict]) -> pd.DataFrame:
    """
    Scan all chunks for markdown tables, extract rows matching METRICS,
    and return a DataFrame with columns: Metric, 2023, 2022, 2021.
    """
    rows: dict[str, dict[str, float | None]] = {}

    for p in payloads:
        content = p.get("content", "")
        if "|" not in content:
            continue
        lines = content.strip().splitlines()

        # Find header row to detect year columns
        header_years: list[str] = []
        header_idx = -1
        for i, line in enumerate(lines):
            cells = [c.strip() for c in line.split("|")]
            year_cells = [c for c in cells if re.fullmatch(r'(?:.*)?20\d{2}(?:.*)?', c)]
            if year_cells:
                header_years = []
                for c in cells:
                    m = re.search(r'(20\d{2})', c)
                    if m:
                        header_years.append(m.group(1))
                header_idx = i
                break

        if not header_years or header_idx < 0:
            continue

        # Parse data rows
        for line in lines[header_idx + 1:]:
            if "---" in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c != ""]
            if len(cells) < 2:
                continue

            label = cells[0].lower().strip()

            for metric_key, display_name in METRICS.items():
                if metric_key in label:
                    if display_name not in rows:
                        rows[display_name] = {}
                    # Map values to years
                    val_cells = cells[1:]
                    # Filter out percentage change columns (contain %)
                    val_cells_clean = [c for c in val_cells if "%" not in c]
                    for j, yr in enumerate(header_years):
                        if j < len(val_cells_clean):
                            v = _parse_number(val_cells_clean[j])
                            if v is not None and yr not in rows[display_name]:
                                rows[display_name][yr] = v
                    break

    if not rows:
        return pd.DataFrame()

    records = []
    for metric, year_vals in rows.items():
        rec = {"Metric": metric}
        for yr in sorted(year_vals.keys(), reverse=True):
            rec[yr] = year_vals[yr]
        records.append(rec)
    return pd.DataFrame(records)


# ── Handle remove actions ─────────────────────────────────────────────────────
if _remove_all:
    if _remove_all_data():
        st.cache_data.clear()
        st.success("All indexed data cleared.")
        st.rerun()
    else:
        st.error("Failed to remove data. Check that the API is running.")


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Loading…"):
    payloads = fetch_chunks()
    df_fin   = extract_financials(payloads)

docs = list(dict.fromkeys(p.get("doc_title", "Unknown") for p in payloads))


# ── Nav pills + Header ───────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom: 16px;">
    <span class="pill-inactive">Query</span>
    <span class="pill-active">Dashboard</span>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<p class="hero-title">Financial Metrics Dashboard<span class="brand-dot">.</span></p>
<p class="hero-sub">Automated extraction from indexed SEC filings and financial reports.</p>
""", unsafe_allow_html=True)


# ── EMPTY STATE — show when no documents are indexed ──────────────────────────
if not payloads:
    st.markdown("""
    <div style="text-align:center; padding: 80px 20px;">
        <div style="font-size: 3rem; margin-bottom: 16px;">📄</div>
        <h2 style="font-size: 1.3rem; font-weight: 700; color: #0f172a; margin-bottom: 8px;">No documents indexed yet</h2>
        <p style="font-size: .92rem; color: #64748b; max-width: 480px; margin: 0 auto 24px;">
            Upload a financial PDF (10-K, annual report, earnings) from the
            <strong>Query</strong> page to see metrics, charts, and analysis here.
        </p>
        <div style="display:inline-block; background: #f0f9ff; border: 1px solid #bfdbfe;
                    border-radius: 10px; padding: 16px 28px; text-align: left; font-size: .82rem; color: #475569;">
            <strong style="color:#0f172a;">How it works:</strong><br>
            1. Go to <strong>Query</strong> page → upload a PDF<br>
            2. Pipeline: Textract → Chunk → Embed → Qdrant<br>
            3. Return here to see extracted financial metrics
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ── Stats row (only shown when data exists) ───────────────────────────────────
st.markdown(f"""
<div class="stat-row">
    <div class="stat-item">
        <div class="stat-label">Indexed Chunks</div>
        <div class="stat-value">{len(payloads):,}</div>
    </div>
    <div class="stat-item">
        <div class="stat-label">Documents</div>
        <div class="stat-value">{len(docs)}</div>
    </div>
    <div class="stat-item">
        <div class="stat-label">Metrics Extracted</div>
        <div class="stat-value">{len(df_fin) if not df_fin.empty else 0}</div>
    </div>
    <div class="stat-item">
        <div class="stat-label">Status</div>
        <div class="stat-value" style="color:#22c55e;">● Live</div>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Per-document removal ──────────────────────────────────────────────────────
if docs:
    with st.expander("Manage documents"):
        for doc in docs:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{doc}**")
            if c2.button("Remove", key=f"rm_{doc}"):
                if _remove_document(doc):
                    st.cache_data.clear()
                    st.success(f"Removed: {doc}")
                    st.rerun()
                else:
                    st.error(f"Failed to remove {doc}")
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── KPI row ───────────────────────────────────────────────────────────────────
def _fmt(val: float | None) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1_000:
        return f"${val:,.0f}M"
    return f"${val:,.2f}"


def _delta(df: pd.DataFrame, metric: str) -> str | None:
    row = df[df["Metric"] == metric]
    if row.empty:
        return None
    cols = [c for c in row.columns if c != "Metric" and c.isdigit()]
    cols_sorted = sorted(cols, reverse=True)
    if len(cols_sorted) >= 2:
        curr = row[cols_sorted[0]].values[0]
        prev = row[cols_sorted[1]].values[0]
        if curr is not None and prev is not None and prev != 0:
            pct = ((curr - prev) / abs(prev)) * 100
            return f"{pct:+.1f}%"
    return None


def _get_val(df: pd.DataFrame, metric: str) -> float | None:
    row = df[df["Metric"] == metric]
    if row.empty:
        return None
    cols = [c for c in row.columns if c != "Metric" and c.isdigit()]
    if cols:
        latest = sorted(cols, reverse=True)[0]
        return row[latest].values[0]
    return None


kpi_list = ["Total Net Sales", "Net Income", "Gross Margin", "Operating Income",
            "R&D Expense", "Cost of Sales", "Cash & Equivalents"]

if not df_fin.empty:
    cols = st.columns(len(kpi_list))
    for col, metric in zip(cols, kpi_list):
        val = _get_val(df_fin, metric)
        col.metric(metric, _fmt(val), delta=_delta(df_fin, metric))
else:
    st.info("No financial tables found in indexed documents.")

st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)


# ── Chart 1: Revenue & Income YoY ────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.markdown('<div class="dash-section"><h3>Revenue vs Income</h3><p class="section-sub">Year-over-year comparison of key revenue and income metrics ($M)</p>', unsafe_allow_html=True)
    chart_metrics = ["Total Net Sales", "Net Income", "Operating Income"]
    if not df_fin.empty:
        chart_rows = df_fin[df_fin["Metric"].isin(chart_metrics)].copy()
        if not chart_rows.empty:
            year_cols = sorted([c for c in chart_rows.columns if c != "Metric" and c.isdigit()])
            if year_cols:
                melted = chart_rows.melt(id_vars="Metric", value_vars=year_cols,
                                         var_name="Year", value_name="Amount ($M)")
                melted = melted.dropna(subset=["Amount ($M)"])
                pivot = melted.pivot(index="Year", columns="Metric", values="Amount ($M)")
                st.bar_chart(pivot)
            else:
                st.info("No year data available.")
        else:
            st.info("Revenue/income metrics not found.")
    else:
        st.info("No data.")
    st.markdown('</div>', unsafe_allow_html=True)

with col_right:
    st.markdown('<div class="dash-section"><h3>Expense Breakdown</h3><p class="section-sub">Cost structure across fiscal years ($M)</p>', unsafe_allow_html=True)
    exp_metrics = ["R&D Expense", "Cost of Sales", "Operating Expenses"]
    if not df_fin.empty:
        chart_rows = df_fin[df_fin["Metric"].isin(exp_metrics)].copy()
        if not chart_rows.empty:
            year_cols = sorted([c for c in chart_rows.columns if c != "Metric" and c.isdigit()])
            if year_cols:
                melted = chart_rows.melt(id_vars="Metric", value_vars=year_cols,
                                         var_name="Year", value_name="Amount ($M)")
                melted = melted.dropna(subset=["Amount ($M)"])
                pivot = melted.pivot(index="Year", columns="Metric", values="Amount ($M)")
                st.bar_chart(pivot)
            else:
                st.info("No year data.")
        else:
            st.info("Expense metrics not found.")
    else:
        st.info("No data.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── Chart 2: Margin % ────────────────────────────────────────────────────────
st.markdown('<div class="dash-section"><h3>Profitability Ratios</h3><p class="section-sub">Gross, operating, and net margins as percentage of total revenue</p>', unsafe_allow_html=True)

if not df_fin.empty:
    year_cols = sorted([c for c in df_fin.columns if c != "Metric" and c.isdigit()])
    rev_row   = df_fin[df_fin["Metric"] == "Total Net Sales"]
    gm_row    = df_fin[df_fin["Metric"] == "Gross Margin"]
    oi_row    = df_fin[df_fin["Metric"] == "Operating Income"]
    ni_row    = df_fin[df_fin["Metric"] == "Net Income"]

    if not rev_row.empty and year_cols:
        pct_rows = []
        for yr in year_cols:
            rev = rev_row[yr].values[0] if yr in rev_row.columns else None
            if rev and rev > 0:
                for label, row_df in [("Gross Margin %", gm_row), ("Operating Margin %", oi_row), ("Net Margin %", ni_row)]:
                    if not row_df.empty and yr in row_df.columns:
                        val = row_df[yr].values[0]
                        if val is not None:
                            pct_rows.append({"Year": yr, "Ratio": label, "Percentage": round(val / rev * 100, 1)})

        if pct_rows:
            df_pct = pd.DataFrame(pct_rows)
            pivot = df_pct.pivot(index="Year", columns="Ratio", values="Percentage")
            st.line_chart(pivot)

            # Show values as table too
            cols_m = st.columns(len(year_cols))
            for col, yr in zip(cols_m, year_cols):
                yr_data = df_pct[df_pct["Year"] == yr]
                lines = [f"**{yr}**"]
                for _, r in yr_data.iterrows():
                    lines.append(f"- {r['Ratio']}: {r['Percentage']}%")
                col.markdown("\n".join(lines))
        else:
            st.info("Not enough data to calculate margins.")
    else:
        st.info("Revenue data not found.")
else:
    st.info("No financial tables found.")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── Full extracted table ──────────────────────────────────────────────────────
st.markdown('<div class="dash-section"><h3>All Extracted Metrics</h3><p class="section-sub">Complete financial data table with year-over-year changes ($M)</p>', unsafe_allow_html=True)
if not df_fin.empty:
    display = df_fin.copy()
    year_cols = sorted([c for c in display.columns if c != "Metric" and c.isdigit()], reverse=True)
    # Add YoY change column
    if len(year_cols) >= 2:
        curr, prev = year_cols[0], year_cols[1]
        display["YoY Change"] = display.apply(
            lambda r: f"{((r[curr] - r[prev]) / abs(r[prev]) * 100):+.1f}%"
            if pd.notna(r.get(curr)) and pd.notna(r.get(prev)) and r.get(prev, 0) != 0
            else "—",
            axis=1,
        )
    # Format numbers
    for col in year_cols:
        display[col] = display[col].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—")
    st.dataframe(display, use_container_width=True, hide_index=True)
else:
    st.info("No financial tables found in indexed documents.")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── Topic & keyword analysis ─────────────────────────────────────────────────
st.markdown('<div class="dash-section"><h3>Topic Coverage</h3><p class="section-sub">Distribution of financial topics across indexed document chunks</p>', unsafe_allow_html=True)

TOPICS = {
    "Revenue & Sales":     ["net sales", "revenue", "total net sales"],
    "Profitability":       ["gross margin", "operating income", "net income", "earnings"],
    "Cash Flow":           ["cash flow", "operating activities", "cash generated", "free cash flow"],
    "Expenses":            ["operating expenses", "cost of sales", "research and development", "r&d"],
    "Debt & Financing":    ["long-term debt", "commercial paper", "term debt", "borrowings"],
    "Shareholders":        ["dividends", "share repurchase", "buyback", "shareholders' equity"],
    "Risk Factors":        ["risk", "litigation", "regulatory", "uncertainty"],
    "International":       ["china", "europe", "japan", "americas", "foreign currencies"],
}

topic_counts: dict[str, int] = {}
for topic, keywords in TOPICS.items():
    count = sum(
        1 for p in payloads
        if any(kw in p.get("content", "").lower() for kw in keywords)
    )
    topic_counts[topic] = count

df_topics = pd.DataFrame(topic_counts.items(), columns=["Topic", "Chunks"]).sort_values("Chunks", ascending=True)
st.bar_chart(df_topics.set_index("Topic"))
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ── Segment breakdown (if available) ─────────────────────────────────────────
st.markdown('<div class="dash-section"><h3>Geographic Revenue</h3><p class="section-sub">Revenue breakdown by reportable geographic segment ($M)</p>', unsafe_allow_html=True)

SEGMENTS = {
    "Americas":             ["americas"],
    "Europe":               ["europe"],
    "Greater China":        ["greater china"],
    "Japan":                ["japan"],
    "Rest of Asia Pacific": ["rest of asia pacific"],
}


def _extract_segment_revenue(payloads: list[dict]) -> dict[str, dict[str, float]]:
    """Find the segment revenue table and extract per-segment figures."""
    result: dict[str, dict[str, float]] = {}
    for p in payloads:
        content = p.get("content", "")
        if "reportable segment" not in content.lower():
            continue
        lines = content.strip().splitlines()
        # Find header years
        header_years = []
        for line in lines:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            for c in cells:
                m = re.search(r'(20\d{2})', c)
                if m and m.group(1) not in header_years:
                    header_years.append(m.group(1))
            if header_years:
                break

        if not header_years:
            continue

        for line in lines:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < 2:
                continue
            label = cells[0].lower()
            for seg_name, keywords in SEGMENTS.items():
                if any(kw in label for kw in keywords):
                    vals = [c for c in cells[1:] if "%" not in c]
                    seg_data = {}
                    for j, yr in enumerate(header_years):
                        if j < len(vals):
                            v = _parse_number(vals[j])
                            if v is not None:
                                seg_data[yr] = v
                    if seg_data:
                        result[seg_name] = seg_data
        if result:
            break
    return result


seg_data = _extract_segment_revenue(payloads)

if seg_data:
    col_seg1, col_seg2 = st.columns(2)

    with col_seg1:
        # Latest year pie chart approximation via bar
        latest_yr = max(set(yr for yrs in seg_data.values() for yr in yrs))
        seg_latest = {seg: vals.get(latest_yr, 0) for seg, vals in seg_data.items()}
        df_seg = pd.DataFrame(seg_latest.items(), columns=["Segment", f"Revenue {latest_yr} ($M)"])
        st.markdown(f'<p style="font-size:.82rem;font-weight:600;color:#475569;margin-bottom:8px;">{latest_yr} Revenue by Segment</p>', unsafe_allow_html=True)
        st.bar_chart(df_seg.set_index("Segment"))

    with col_seg2:
        # YoY per segment
        all_years = sorted(set(yr for yrs in seg_data.values() for yr in yrs))
        records = []
        for seg, yrs in seg_data.items():
            for yr in all_years:
                if yr in yrs:
                    records.append({"Year": yr, "Segment": seg, "Revenue ($M)": yrs[yr]})
        if records:
            df_seg_yoy = pd.DataFrame(records)
            pivot = df_seg_yoy.pivot(index="Year", columns="Segment", values="Revenue ($M)")
            st.markdown('<p style="font-size:.82rem;font-weight:600;color:#475569;margin-bottom:8px;">Segment Revenue Trend</p>', unsafe_allow_html=True)
            st.line_chart(pivot)
else:
    st.info("No geographic segment data found.")
st.markdown('</div>', unsafe_allow_html=True)
