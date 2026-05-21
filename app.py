"""
Smart Tool Log Parser — Streamlit Dashboard
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import config
from parser import parse_log
from database import db
from llm import analyzer
from synthetic.generator import generate_sample_files
import streamlit.components.v1
import re
import time
import uuid

from worker import start_background_parsing

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def is_valid_log_file(file_bytes: bytes, filename: str) -> bool:
    """
    Validates if the uploaded file is a plausible semiconductor fab log.
    Rejects: emoji/ASCII-art files, non-log binaries, and content
    with zero relevance to equipment/process logging.
    """
    filename_lower = filename.lower()

    # 1. Hard rejection of explicit non-log binaries and documents
    invalid_extensions = [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".pdf", ".docx", ".xlsx", ".pptx",
        ".exe", ".dll", ".msi",
        ".zip", ".tar", ".gz", ".7z", ".rar",
        ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ]
    if any(filename_lower.endswith(ext) for ext in invalid_extensions):
        return False

    # 2. Fast-pass for standard and known proprietary extensions
    valid_extensions = [
        ".log", ".txt", ".csv", ".json", ".xml", ".tsv",
        ".bin", ".dat", ".raw", ".prc", ".parquet",
    ]
    has_valid_ext = any(filename_lower.endswith(ext) for ext in valid_extensions)

    # 3. Content heuristics (evaluate first 1024 bytes for quick checks)
    sample_bytes = file_bytes[:1024]

    # Heuristic A: Binary payload detection
    # Proprietary fab formats often contain null bytes.
    if b"\x00" in sample_bytes:
        return True

    # 4. Text-based heuristics
    sample_text = sample_bytes.decode("utf-8", errors="ignore")

    # Heuristic B: Emoji rejection (very low threshold — fab logs should have none)
    emoji_pattern = re.compile("[\U00010000-\U0010ffff]", flags=re.UNICODE)
    emoji_count = len(emoji_pattern.findall(sample_text))
    if emoji_count > 2:
        return False

    # Heuristic C: Common emoji shortcodes / emoticons in text
    emoticon_pattern = re.compile(
        r"[:;]['\-]?[)(DPp/\\|]|[<>]3|xD|XD|\bლ\b|¯\\?_\(ツ\)_/¯|"
        r"[\U0000231A-\U0000232A]|[\U000023E9-\U000023F3]|[\U000025AA-\U000025AB]|"
        r"[\U00002600-\U000027BF]|[\U0000FE00-\U0000FE0F]|[\U0001F000-\U0001FAFF]",
        re.UNICODE,
    )
    if len(emoticon_pattern.findall(sample_text)) > 5:
        return False

    # Heuristic D: ASCII art / decorative text detection
    # Reject files with heavy box-drawing, repeated decorative characters, or figlet-style art
    ascii_art_indicators = [
        r"[═║╔╗╚╝╠╣╦╩╬]{3,}",              # box-drawing characters
        r"[─│┌┐└┘├┤┬┴┼]{5,}",              # light box-drawing
        r"[*#=\-~_]{10,}",                   # long decorative lines (10+ chars)
        r"[/\\|]{5,}",                        # repeated slashes (art patterns)
        r"(?:\.{5,}\s*){2,}",                # dot leaders / art
        r"[░▒▓█]{3,}",                       # block elements
        r"[♠♣♥♦★☆●○◆◇]{3,}",               # decorative symbols
        r"(?:\^[_v]\^|\(╯°□°\)╯|ʕ•ᴥ•ʔ)",    # kaomoji / text faces
    ]
    ascii_art_hits = sum(
        1 for pat in ascii_art_indicators
        if re.search(pat, sample_text)
    )
    if ascii_art_hits >= 2:
        return False

    # 5. Semiconductor fab relevance gate
    # Scan a larger sample (up to 4 KB) for domain-specific keywords.
    # Files with ZERO fab-relevant terms are rejected as unrelated content.
    extended_text = file_bytes[:4096].decode("utf-8", errors="ignore").lower()

    fab_keywords = [
        # Equipment & tools
        r"\btool[_\s]?id\b", r"\bmachine[_\s]?id\b", r"\bequip", r"\bchamber\b",
        r"\bdevice[_\s]?id\b", r"\bhost\b",
        # Process
        r"\bwafer\b", r"\blot[_\s]?id\b", r"\brecipe\b", r"\bsetpoint\b",
        r"\bprocess[_\s]?(step|stage|phase)\b", r"\betch\b", r"\bdeposit\b",
        r"\banneal\b", r"\bclean\b", r"\bsputt", r"\bcvd\b", r"\bpvd\b",
        # Sensors / parameters
        r"\bpressure\b", r"\btemperature\b", r"\bflow[_\s]?rate\b", r"\bvacuum\b",
        r"\brf[_\s]?power\b", r"\btorr\b", r"\brpm\b", r"\bsccm\b",
        r"\bvoltage\b", r"\bcurrent\b", r"\bpower\b",
        # Log severity / events
        r"\b(info|warn|error|critical|debug|fault|alarm)\b",
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}",  # ISO timestamp
        r"\btimestamp\b", r"\bseverity\b", r"\blog[_\s]?(type|level)\b",
        # Fab-specific
        r"\bpm\b", r"\bmaintenan", r"\bcalibrat", r"\bsensor\b",
        r"\bsubstrate\b", r"\bfoup\b", r"\bloadlock\b", r"\bendpoint\b",
    ]

    fab_hits = sum(
        1 for kw in fab_keywords
        if re.search(kw, extended_text)
    )

    # Require at least 2 fab-relevant keyword matches
    if fab_hits < 2:
        # Last chance: if it has a valid log extension AND structured data markers,
        # allow it (could be a generic structured log from fab equipment)
        if has_valid_ext:
            log_markers = [
                r"\d{4}-\d{2}-\d{2}",
                r"\{.*\}",
                r"<.*>",
                r"ERROR|INFO|WARN|DEBUG",
                r"0x[0-9a-fA-F]+",
                r"\[.*\]",
            ]
            if any(re.search(m, sample_text, re.IGNORECASE) for m in log_markers):
                return True
        return False

    # Heuristic F: Look for common log markers if no valid extension is present
    if not has_valid_ext:
        log_markers = [
            r"\d{4}-\d{2}-\d{2}",
            r"\{.*\}",
            r"<.*>",
            r"ERROR|INFO|WARN|DEBUG|FAULT",
            r"0x[0-9a-fA-F]+",
            r"\[.*\]",
        ]
        if not any(
            re.search(marker, sample_text, re.IGNORECASE) for marker in log_markers
        ):
            if not re.search(r"\d", sample_text):
                return False

    return True

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Smart Tool Log Parser",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — industrial dark theme
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
@import url\
    ('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

/* Base Typography */
html, body, [class*="css"], .stMarkdown { font-family: 'Inter', sans-serif !important; }
.stApp { background-color: #0d1117; color: #c9d1d9; }

/* Headers */
h1, h2, h3, h4, h5, h6 { font-family: 'Inter', sans-serif !important; font-weight: 600 !important; \
    color: #e6edf3; letter-spacing: -0.01em; }
h1 { font-weight: 700 !important; letter-spacing: -0.02em; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #161b22;
    border-right: 1px solid #30363d;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 6px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06);
}
[data-testid="metric-container"] label { color: #8b949e !important; font-size: 0.8rem !important; \
font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
[data-testid="stMetricValue"] { color: #58a6ff !important; font-family: 'JetBrains Mono', \
monospace !important; font-size: 2.2rem !important; font-weight: 600; }

/* Dataframe */
[data-testid="stDataFrame"] { border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
[data-testid="stDataFrame"] > div { border-radius: 8px; }

/* Buttons */
.stButton > button {
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    font-weight: 500;
    transition: all 0.2s ease;
}
.stButton > button:hover { background: #30363d; border-color: #8b949e; color: #ffffff; }

/* Primary button (Quick Actions / Highlights) */
.stButton > button[kind="primary"] {
    background: #238636;
    color: #ffffff;
    border: 1px solid rgba(240, 246, 252, 0.1);
}
.stButton > button[kind="primary"]:hover {
    background: #2ea043;
    border-color: rgba(240, 246, 252, 0.1);
}

/* Tab styling */
[data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #30363d !important; }
[data-baseweb="tab"] {
    background: transparent;
    color: #8b949e;
    border-radius: 6px 6px 0 0;
    font-size: 0.9rem;
    font-weight: 500;
    padding-top: 12px;
    padding-bottom: 12px;
}
[aria-selected="true"][data-baseweb="tab"] { background: #161b22 !important; \
color: #e6edf3 !important; border-bottom: 2px solid #58a6ff !important; }

/* File uploader */
[data-testid="stFileUploader"] {
    border: 1px dashed #30363d;
    border-radius: 8px;
    padding: 16px;
    background: #0d1117;
}

/* Code/mono text */
code { font-family: 'JetBrains Mono', monospace !important; background: #161b22; \
padding: 3px 6px; border-radius: 4px; font-size: 0.85rem; color: #79c0ff; \
border: 1px solid #30363d; }

/* Alert boxes */
.stAlert { border-radius: 8px; border: 1px solid #30363d; }

/* Divider */
hr { border-color: #30363d; margin: 1.5rem 0; }

/* Inputs */
.stSelectbox > div > div, .stTextInput > div > input, [data-testid="stChatInput"] {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    color: #c9d1d9 !important;
    border-radius: 6px !important;
}
.stSelectbox > div > div:focus-within, .stTextInput > div > input:focus, \
    [data-testid="stChatInput"]:focus-within {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 1px #58a6ff !important;
}

/* Chat message bubbles */
[data-testid="stChatMessage"] { background-color: transparent; }

/* Typing indicator */
.typing-indicator {
  display: inline-flex;
  align-items: center;
  padding: 12px 8px;
  background: #161b22;
  border-radius: 8px;
  border: 1px solid #30363d;
  width: fit-content;
}
.typing-indicator span {
  display: inline-block;
  width: 6px;
  height: 6px;
  background-color: #8b949e;
  border-radius: 50%;
  margin: 0 4px;
  animation: typing 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Init DB
# ---------------------------------------------------------------------------

db.init_db()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "parsed_filenames" not in st.session_state:
    st.session_state.parsed_filenames = []
if "last_filename" not in st.session_state:
    st.session_state.last_filename = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image("./assets/logo.png", width="stretch")
    st.divider()

    st.markdown("### 📁 Upload Log Files")
    uploaded_files = st.file_uploader(
        "Supports mixed formats concurrently (JSON, Parquet, CSV, Syslog, Hex, etc.)",
        accept_multiple_files=True,
        type=None,
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("### 🧪 Demo Logs")
    if st.button("Generate Synthetic Logs", width="stretch"):
        with st.spinner("Generating..."):
            files = generate_sample_files("synthetic/samples")
            st.session_state["demo_files"] = files
        st.success("✓ 5 format samples ready in sidebar")

    if "demo_files" in st.session_state:
        st.caption("Load a demo file:")
        for fmt, path in st.session_state["demo_files"].items():
            if st.button(f"  {fmt.upper()}", key=f"demo_{fmt}", width="stretch"):
                with open(path, "rb") as f:
                    content_bytes = f.read()
                filename = os.path.basename(path)
                with st.spinner(f"Parsing {filename}..."):
                    db.delete_by_filename(filename)
                    entries, warnings = parse_log(content_bytes, filename)
                    n = db.insert_entries(entries)
                    if filename not in st.session_state.parsed_filenames:
                        st.session_state.parsed_filenames.append(filename)
                    st.session_state.last_filename = filename
                st.success(f"✓ {n} rows stored")
                if warnings:
                    for w in warnings[:5]:
                        st.warning(w)

    st.divider()
    st.markdown("### 🗄️ Database")
    if st.button("Clear All Data", width="stretch"):
        db.clear_all()
        st.session_state.parsed_filenames = []
        st.session_state.last_filename = None
        st.session_state.chat_messages = []
        st.rerun()

    st.divider()

# ---------------------------------------------------------------------------
# Handle multi-file upload (batch jobs)
# ---------------------------------------------------------------------------

if "active_job_ids" not in st.session_state:
    st.session_state.active_job_ids = []
if "processed_file_ids" not in st.session_state:
    st.session_state.processed_file_ids = set()

if uploaded_files:
    for uploaded_file in uploaded_files:
        if uploaded_file.file_id in st.session_state.processed_file_ids:
            continue

        content_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

        if not is_valid_log_file(content_bytes, filename):
            st.error(f"❌ **Rejected:** `{filename}` failed validation heuristics.")
            st.session_state.processed_file_ids.add(uploaded_file.file_id)
            continue

        job_id = str(uuid.uuid4())
        db.create_job(job_id, filename)
        start_background_parsing(content_bytes, filename, job_id)
        st.session_state.active_job_ids.append(job_id)
        st.session_state.processed_file_ids.add(uploaded_file.file_id)
        st.session_state.chat_messages = []

if st.session_state.active_job_ids:
    st.markdown("### ⚙️ Processing Batch Queue")
    jobs_to_remove = []
    has_active_jobs = False

    for job_id in st.session_state.active_job_ids:
        job_state = db.get_job(job_id)
        if not job_state:
            jobs_to_remove.append(job_id)
            continue

        filename = job_state["filename"]
        status = job_state["status"]
        progress = job_state["progress"]
        error_msg = job_state["error_message"]
        total_records = job_state["total_records"]

        if status in ["PENDING", "PROCESSING"]:
            has_active_jobs = True
            st.caption(f"**{filename}** - {status} ({progress}%)")
            st.progress(progress / 100.0)
        elif status == "COMPLETED":
            st.success(
                f"✅ **{filename}:** Normalised and stored **{total_records or 0}** rows."
            )
            st.session_state.last_filename = filename
            if filename not in st.session_state.parsed_filenames:
                st.session_state.parsed_filenames.append(filename)
            jobs_to_remove.append(job_id)
        elif status == "FAILED":
            st.error(f"❌ **{filename}:** Pipeline aborted - {error_msg}")
            jobs_to_remove.append(job_id)

    for jid in jobs_to_remove:
        st.session_state.active_job_ids.remove(jid)

    if has_active_jobs:
        time.sleep(1.0)
        st.rerun()

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# Header
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown("# ⚙️ Smart Tool Log Parser")
    st.caption("Semiconductor Equipment Log Intelligence Platform")
with col_h2:
    active_file = st.session_state.last_filename
    if active_file:
        st.markdown(f"**Active file:** `{active_file}`")
        all_files = st.session_state.parsed_filenames
        if len(all_files) > 1:
            selected_file = st.selectbox(
                "Switch file", all_files, index=all_files.index(active_file)
            )
            if selected_file != active_file:
                st.session_state.last_filename = selected_file
                st.session_state.chat_messages = []  # clear chat on file switch
                active_file = selected_file

# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------

stats = db.get_summary_stats(active_file)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Entries", f"{stats['total']:,}")
c2.metric("Unique Tools", stats["tools"])
c3.metric("🔴 Alarms", stats["alarms"])
c4.metric("⚠️ Errors", stats["errors"])
c5.metric("🟡 Warnings", stats["warnings"])
c6.metric("📋 Recipes", stats.get("recipes", 0))

st.divider()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

with st.expander("🔍 Filters", expanded=True):
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    all_tools = ["All"] + db.get_distinct_values("tool_id", active_file)
    all_sevs = ["All"] + db.get_distinct_values("severity", active_file)
    all_types = ["All"] + db.get_distinct_values("log_type", active_file)
    all_fmts = ["All"] + db.get_distinct_values("source_format", active_file)

    f_tool = fc1.selectbox("Tool ID", all_tools)
    f_sev = fc2.selectbox("Severity", all_sevs)
    f_type = fc3.selectbox("Log Type", all_types)
    f_fmt = fc4.selectbox("Format", all_fmts)
    f_search = fc5.text_input("🔎 Search", placeholder="alarm, wafer, recipe...")

    filter_kwargs = dict(
        tool_id=None if f_tool == "All" else f_tool,
        severity=None if f_sev == "All" else f_sev,
        log_type=None if f_type == "All" else f_type,
        source_filename=active_file,
        search=f_search or None,
    )
    if f_fmt != "All":
        filter_kwargs["source_format"] = f_fmt  # extend query if needed

rows = db.query_entries(**filter_kwargs, limit=500)
df = pd.DataFrame(rows) if rows else pd.DataFrame()
if not df.empty and "parameter_value" in df.columns:
    df["parameter_value"] = pd.to_numeric(df["parameter_value"], errors="coerce")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📋 Parsed Logs",
        "📊 Analytics",
        "🤖 AI Insights",
        "📖 Schema Reference",
    ]
)

# ─────────────────────── TAB 1: Parsed Logs ────────────────────────────────
with tab1:
    if df.empty:
        st.info("No data yet — upload a log file or load a demo log from the sidebar.")
    else:
        display_cols = [
            "timestamp",
            "tool_id",
            "severity",
            "log_type",
            "event_name",
            "parameter_name",
            "parameter_value",
            "unit",
            "wafer_id",
            "recipe_id",
            "step_number",
            "drain_cluster_id",
            "source_format",
            "normalized_message",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        def _style_severity(val):
            colors = {
                "CRITICAL": "#ff7b72",
                "ERROR": "#f78166",
                "WARNING": "#cda869",
                "INFO": "#58a6ff",
                "DEBUG": "#8b949e",
            }
            return f"color: {colors.get(str(val).upper(), '#c9d1d9')}"

        styled = df[display_cols].style.map(_style_severity, subset=["severity"])
        st.dataframe(styled, width="stretch", height=480)

        # Download
        csv_export = df[display_cols].to_csv(index=False)
        st.download_button(
            "⬇️ Export CSV",
            csv_export,
            file_name=f"parsed_logs_{active_file or 'all'}.csv",
            mime="text/csv",
        )

# ─────────────────────── TAB 2: Analytics ──────────────────────────────────
with tab2:
    if df.empty:
        st.info("Upload logs to see analytics.")
    else:
        col_l, col_r = st.columns(2)

        # Severity distribution (donut)
        with col_l:
            sev_counts = df["severity"].value_counts().reset_index()
            sev_counts.columns = ["severity", "count"]
            SEV_COLORS = {
                "CRITICAL": "#ff7b72",
                "ERROR": "#f78166",
                "WARNING": "#cda869",
                "INFO": "#58a6ff",
                "DEBUG": "#8b949e",
            }
            fig_sev = px.pie(
                sev_counts,
                names="severity",
                values="count",
                title="Log Severity Distribution",
                hole=0.5,
                color="severity",
                color_discrete_map=SEV_COLORS,
            )
            fig_sev.update_layout(
                paper_bgcolor="#0d0f14",
                plot_bgcolor="#0d0f14",
                font_color="#c9d1d9",
                legend_bgcolor="#0d0f14",
            )
            st.plotly_chart(fig_sev, width="stretch")

        # Log type breakdown (horizontal bar)
        with col_r:
            type_counts = df["log_type"].value_counts().reset_index()
            type_counts.columns = ["log_type", "count"]
            fig_type = px.bar(
                type_counts,
                x="count",
                y="log_type",
                orientation="h",
                title="Events by Log Type",
                color="count",
                color_continuous_scale=["#1e4070", "#58a6ff"],
            )
            fig_type.update_layout(
                paper_bgcolor="#0d0f14",
                plot_bgcolor="#141820",
                font_color="#c9d1d9",
                showlegend=False,
                yaxis=dict(autorange="reversed"),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_type, width="stretch")

        # Events over time
        if "timestamp" in df.columns:
            df_time = df.dropna(subset=["timestamp"]).copy()
            df_time["timestamp"] = pd.to_datetime(df_time["timestamp"], errors="coerce")
            df_time = df_time.dropna(subset=["timestamp"])

            if not df_time.empty:
                df_time["hour"] = df_time["timestamp"].dt.floor("h")
                time_counts = (
                    df_time.groupby(["hour", "severity"])
                    .size()
                    .reset_index(name="count")
                )

                # Changed to px.line, reverted x to hour and y to count
                fig_time = px.line(
                    time_counts,
                    x="hour",
                    y="count",
                    color="severity",
                    title="Log Volume Over Time (hourly)",
                    color_discrete_map=SEV_COLORS,
                    markers=True,  # Adds dots to each data point for better visibility
                )

                # Reverted xaxis_title and yaxis_title to standard time-series layout
                fig_time.update_layout(
                    paper_bgcolor="#0d0f14",
                    plot_bgcolor="#141820",
                    font_color="#c9d1d9",
                    legend_bgcolor="#0d0f14",
                    xaxis_title="Time",
                    yaxis_title="Count",
                )
        st.plotly_chart(fig_time, width="stretch")

        # Alarms per tool
        alarm_df = (
            df[df["log_type"] == "alarm"]
            if "log_type" in df.columns
            else pd.DataFrame()
        )
        if not alarm_df.empty:
            tool_alarms = alarm_df["tool_id"].value_counts().reset_index()
            tool_alarms.columns = ["tool_id", "alarm_count"]
            fig_ta = px.bar(
                tool_alarms,
                x="tool_id",
                y="alarm_count",
                title="Alarms per Tool",
                color="alarm_count",
                color_continuous_scale=["#1e4070", "#ff7b72"],
            )
            fig_ta.update_layout(
                paper_bgcolor="#0d0f14",
                plot_bgcolor="#141820",
                font_color="#c9d1d9",
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_ta, width="stretch")

        # Sensor line chart (desaturated at rest, saturated on hover)
        sensor_df = (
            df.dropna(subset=["parameter_value"])
            if "parameter_value" in df.columns
            else pd.DataFrame()
        )
        if not sensor_df.empty and "timestamp" in sensor_df.columns:
            sensor_df = sensor_df.copy()
            sensor_df["timestamp"] = pd.to_datetime(
                sensor_df["timestamp"], errors="coerce"
            )
            sensor_df = sensor_df.dropna(subset=["timestamp"]).sort_values("timestamp")

            if not sensor_df.empty:
                params_available = (
                    sensor_df["parameter_name"].dropna().unique().tolist()
                )
                chosen_param = st.selectbox("Sensor to plot", params_available)

                p_df = sensor_df[sensor_df["parameter_name"] == chosen_param].copy()
                tools_in_param = p_df["tool_id"].dropna().unique().tolist()

                SAT = [
                    "#58a6ff",
                    "#3fb950",
                    "#e3b341",
                    "#bc8cff",
                    "#39d0d0",
                    "#ff7b72",
                    "#79c0ff",
                    "#d29922",
                ]
                sat_map = {t: SAT[i % len(SAT)] for i, t in enumerate(tools_in_param)}

                fig_sensor = go.Figure()
                for tool in tools_in_param:
                    t_df = p_df[p_df["tool_id"] == tool].sort_values("timestamp")
                    fig_sensor.add_trace(
                        go.Scatter(
                            x=t_df["timestamp"],
                            y=t_df["parameter_value"],
                            mode="lines+markers",
                            name=tool,
                            line=dict(
                                color=sat_map[tool],
                                width=2,
                                shape="spline",
                                smoothing=0.99,
                            ),
                            marker=dict(color=sat_map[tool], size=5),
                            hovertemplate=(
                                f"<b>{tool}</b><br>"
                                "%{x|%Y-%m-%d %H:%M:%S}<br>"
                                f"{chosen_param}: %{{y}}<extra></extra>"
                            ),
                        )
                    )

                # ── Animation frames ───────────────────────────────────────
                all_times = sorted(p_df["timestamp"].unique())
                frames, slider_steps = [], []
                for i, cutoff in enumerate(all_times):
                    frame_traces = []
                    for tool in tools_in_param:
                        t_df = p_df[
                            (p_df["tool_id"] == tool) & (p_df["timestamp"] <= cutoff)
                        ]
                        frame_traces.append(
                            go.Scatter(
                                x=t_df["timestamp"],
                                y=t_df["parameter_value"],
                                mode="lines+markers",
                                line=dict(color=sat_map[tool], width=2.5),
                                marker=dict(color=sat_map[tool], size=6),
                            )
                        )
                    frames.append(go.Frame(data=frame_traces, name=str(i)))
                    slider_steps.append(
                        dict(
                            args=[
                                [str(i)],
                                {
                                    "frame": {"duration": 60, "redraw": True},
                                    "mode": "immediate",
                                },
                            ],
                            label="",
                            method="animate",
                        )
                    )
                fig_sensor.frames = frames

                fig_sensor.update_layout(
                    paper_bgcolor="#0d1117",
                    plot_bgcolor="#0d1117",
                    font_color="#c9d1d9",
                    legend=dict(
                        bgcolor="#161b22", bordercolor="#30363d", borderwidth=1
                    ),
                    xaxis=dict(gridcolor="#1e2730", zeroline=False, title="Time"),
                    yaxis=dict(gridcolor="#1e2730", zeroline=False, title=chosen_param),
                    title=dict(
                        text=f"{chosen_param.capitalize()} Readings over Time",  # pyright: ignore[reportAttributeAccessIssue] # noqa: E501
                        font=dict(size=15, color="#e6edf3"),
                    ),
                    # Native Plotly hover line — draws a vertical rule across all traces
                    hovermode="x unified",
                    # This is the native Plotly feature that dims non-hovered traces
                    hoverdistance=30,
                    margin=dict(t=80, b=60),
                    updatemenus=[
                        dict(
                            type="buttons",
                            showactive=False,
                            x=0.05,
                            y=1.08,
                            xanchor="left",
                            yanchor="top",
                            bgcolor="#21262d",
                            bordercolor="#30363d",
                            font=dict(color="#c9d1d9", size=12),
                            buttons=[
                                dict(
                                    label="▶  Play",
                                    method="animate",
                                    args=[
                                        None,
                                        {
                                            "frame": {"duration": 60, "redraw": True},
                                            "transition": {
                                                "duration": 40,
                                                "easing": "linear",
                                            },
                                            "fromcurrent": True,
                                            "mode": "immediate",
                                        },
                                    ],
                                ),
                                dict(
                                    label="⏸  Pause",
                                    method="animate",
                                    args=[
                                        [None],
                                        {
                                            "frame": {"duration": 0, "redraw": False},
                                            "mode": "immediate",
                                            "transition": {"duration": 0},
                                        },
                                    ],
                                ),
                            ],
                        )
                    ],
                    sliders=[
                        dict(
                            steps=slider_steps,
                            active=0,
                            x=0.0,
                            y=0,
                            len=1.0,
                            bgcolor="#161b22",
                            bordercolor="#30363d",
                            tickcolor="#30363d",
                            font=dict(color="#8b949e", size=10),
                            currentvalue=dict(visible=False),
                            transition=dict(duration=0),
                        )
                    ],
                )

                st.plotly_chart(
                    fig_sensor,
                    width="stretch",
                    key=f"sensor_{chosen_param.replace(' ', '_')}",  # pyright: ignore[reportAttributeAccessIssue] # noqa: E501
                )

        st.divider()
        st.markdown("### 🔬 Root Cause Sequence Analysis")
        st.caption("Select a critical fault to view the preceding temporal events.")

        error_query = (
            "SELECT id, timestamp, tool_id, "
            "COALESCE(json_extract(metadata, '$.event_name'), raw_message) as event_name, "
            "drain_cluster_id "
            "FROM log_entries "
            "WHERE severity IN ('ERROR', 'CRITICAL') AND source_filename = ? "
            "ORDER BY timestamp DESC"
        )
        with db._get_conn() as conn:
            error_df = pd.read_sql_query(error_query, conn, params=(active_file,))

        if not error_df.empty:
            # Truncate long event names for the dropdown
            error_df["display_name"] = error_df["event_name"].apply(
                lambda x: (x[:80] + "…") if isinstance(x, str) and len(x) > 80 else x
            )
            error_options = (
                error_df.apply(
                    lambda x: f"[{x['timestamp']}] {x['tool_id']} — {x['display_name']}",
                    axis=1,
                ).tolist()
            )
            selected_error_str = st.selectbox("Target Fault:", error_options)

            if selected_error_str:
                sel_idx = error_options.index(selected_error_str)
                target_row = error_df.iloc[sel_idx]
                t_time = target_row["timestamp"]
                t_tool = target_row["tool_id"]

                seq_query = """
                    SELECT timestamp, severity, log_type,
                           json_extract(metadata, '$.parameter_name') as parameter_name,
                           json_extract(metadata, '$.parameter_value') as parameter_value,
                           json_extract(metadata, '$.unit') as unit,
                           COALESCE(json_extract(metadata, '$.event_name'), raw_message) as event_name,
                           drain_cluster_id,
                           raw_message
                    FROM log_entries
                    WHERE tool_id = ? AND timestamp <= ? AND source_filename = ?
                    ORDER BY timestamp DESC LIMIT 20
                """
                with db._get_conn() as conn:
                    seq_df = pd.read_sql_query(
                        seq_query, conn, params=(t_tool, t_time, active_file)
                    )

                seq_df = seq_df.sort_values(by="timestamp", ascending=True)
                if "parameter_value" in seq_df.columns:
                    seq_df["parameter_value"] = pd.to_numeric(seq_df["parameter_value"], errors="coerce")

                # Truncate raw_message for display
                if "raw_message" in seq_df.columns:
                    seq_df["raw_message"] = seq_df["raw_message"].apply(
                        lambda x: (x[:120] + "…") if isinstance(x, str) and len(x) > 120 else x
                    )

                # Drop columns that are entirely NULL (cleaner for unstructured-only data)
                seq_df = seq_df.dropna(axis=1, how="all")

                def highlight_target(row):
                    if row["timestamp"] == t_time:
                        return ["background-color: rgba(255, 99, 71, 0.2)"] * len(row)
                    return [""] * len(row)

                st.dataframe(seq_df.style.apply(highlight_target, axis=1), width="stretch")

                # Show cluster context if drain_cluster_id exists on the target fault
                target_cluster = target_row.get("drain_cluster_id")
                if target_cluster is not None:
                    st.caption(f"🔗 Drain3 Cluster ID: **{int(target_cluster)}** — "
                               "other events sharing this template pattern may indicate recurring issues.")
        else:
            st.info(
                "No critical faults detected in the current log file to perform RCA."
            )
# ─────────────────────── TAB 3: AI Insights ────────────────────────────────
with tab3:
    if not config.OPENAI_API_KEY:
        st.warning(
            "⚠️ OpenAI API key must be set in the .env file in \
                the project root to enable AI features."
        )
    elif df.empty:
        st.info("Upload logs first to chat with your data.")
    else:
        st.markdown("### 📑 Executive Shift Report")
        if st.button(
            "Generate Shift Summary Report",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Aggregating metrics and generating executive summary..."):
                with db._get_conn() as conn:
                    anomalies = pd.read_sql_query(
                        """
                        SELECT COALESCE(json_extract(metadata, '$.event_name'), raw_message) as event_name,
                               COUNT(*) as freq
                        FROM log_entries
                        WHERE severity IN ('ERROR', 'CRITICAL') AND source_filename = ?
                        GROUP BY event_name
                        ORDER BY freq DESC
                        LIMIT 5
                        """,
                        conn,
                        params=(active_file,),
                    ).to_dict(orient="records")

                report_context = {
                    "Total Logs": stats.get("total", 0),
                    "Error Count": stats.get("errors", 0),
                    "Alarm Count": stats.get("alarms", 0),
                    "Affected Tools": db.get_distinct_values("tool_id", active_file),
                    "Most Frequent Anomalies": anomalies,
                }

                prompt = f"""
Act as a Semiconductor Fab Operations Manager. Review the following shift metrics:
{report_context}

Generate a concise, 3-section Markdown report:
1. **Shift Overview**: 2 sentences on general stability.
2. **Critical Excursions**: Bullet points detailing the highest frequency errors.
3. **Recommended Actions**: 2 actionable engineering steps based on the anomalies.
"""

                response = analyzer.generate_text(prompt, max_tokens=600)

                st.success("Report Generated")
                st.markdown(response)

        st.divider()

        st.markdown("### 🤖 Chat with Your Log Data")
        st.caption(
            "Ask questions about the active log file, its anomalies, tool performance, and errors."
        )

        # Display chat messages from history on app rerun
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Accept user input
        chat_prompt = st.chat_input(f"Ask about {active_file}...")

        # If it's a new conversation, offer context-aware quick actions
        if not st.session_state.chat_messages:
            st.markdown("**💡 Predicted Quests (Automated Insights):**")
            suggestions = ["Summarise the overall health of these logs."]
            if stats.get("errors", 0) > 0:
                suggestions.append(
                    f"What might be causing the {stats['errors']} errors?"
                )
            elif stats.get("warnings", 0) > 0:
                suggestions.append(
                    f"Highlight the {stats['warnings']} warnings present."
                )

            if stats.get("alarms", 0) > 0:
                suggestions.append("Detail the alarms and their potential root causes.")
            if stats.get("tools", 0) > 1:
                suggestions.append("Compare the performance across different tools.")

            cols = st.columns(min(len(suggestions), 4))
            for i, sug in enumerate(suggestions[:4]):
                if cols[i].button(sug, key=f"sug_{i}", width="stretch"):
                    st.session_state.chat_messages.append(
                        {"role": "user", "content": sug}
                    )
                    st.rerun()

        if chat_prompt:
            st.session_state.chat_messages.append(
                {"role": "user", "content": chat_prompt}
            )
            st.rerun()

        # If the last message is from the user, generate the assistant's response
        if (
            st.session_state.chat_messages
            and st.session_state.chat_messages[-1]["role"] == "user"
        ):
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                message_placeholder.markdown(
                    '<div class="typing-indicator"><span></span><span></span><span></span></div>',
                    unsafe_allow_html=True,
                )

                # Give LLM a sample of the data (up to 30 rows) to keep token size in check
                sample_rows = df.head(30).to_dict(orient="records")
                response = analyzer.chat_with_logs(
                    st.session_state.chat_messages, stats, sample_rows
                )

                message_placeholder.markdown(response)

            # Add assistant response to chat history
            st.session_state.chat_messages.append(
                {"role": "assistant", "content": response}
            )
            st.rerun()

# ─────────────────────── TAB 4: Schema Reference ───────────────────────────
with tab4:
    st.markdown("### 📐 Normalised Log Schema")
    st.caption(
        "Every log entry — regardless of source format — is mapped to this standard structure."
    )

    schema_info = [
        ("id", "TEXT", "✅ Auto", "Unique record UUID"),
        ("timestamp", "TEXT", "✅ Req", "ISO-8601 event timestamp"),
        ("tool_id", "TEXT", "✅ Req", "Equipment / machine identifier"),
        (
            "log_type",
            "TEXT",
            "Auto",
            "process_step | alarm | sensor_reading | maintenance | info",
        ),
        ("severity", "TEXT", "✅ Req", "DEBUG | INFO | WARNING | ERROR | CRITICAL"),
        ("event_name", "JSON→TEXT", "Optional", "Human-readable event description (in metadata)"),
        ("recipe_id", "TEXT", "Optional", "Process recipe identifier"),
        ("wafer_id", "TEXT", "Optional", "Wafer / lot identifier"),
        ("process_stage", "TEXT", "Optional", "LOAD | PROCESS | VENT | UNLOAD etc."),
        ("step_number", "INTEGER", "Optional", "Process step or stage number"),
        ("parameter_name", "TEXT", "Optional", "Normalised sensor/parameter name"),
        ("parameter_value", "REAL", "Optional", "Numeric sensor reading"),
        ("unit", "TEXT", "Optional", "Unit of measurement"),
        ("raw_message", "TEXT", "✅ Req", "Original log line / message"),
        ("normalized_message", "TEXT", "Auto", "Cleaned human-readable version"),
        ("drain_cluster_id", "INTEGER", "Auto", "Drain3 cluster/template ID"),
        ("source_format", "TEXT", "Auto", "json | csv | xml | syslog | text"),
        ("source_filename", "TEXT", "Auto", "Originating filename"),
        ("ai_summary", "TEXT", "LLM", "AI-generated plain English summary"),
        ("ai_classification", "TEXT", "LLM", "normal | warning | anomaly | fault"),
        ("ai_root_cause_hint", "TEXT", "LLM", "Possible cause / troubleshooting hint"),
    ]

    schema_df = pd.DataFrame(
        schema_info, columns=["Field", "Type", "Status", "Description"]
    )
    st.dataframe(schema_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("### 🔄 Supported Input Formats")
    fmt_info = [
        ("JSON", "Structured", ".json", "Array or newline-delimited JSON objects"),
        (
            "CSV",
            "Structured",
            ".csv / .tsv",
            "Header row required; comma or tab delimited",
        ),
        ("XML", "Structured", ".xml", "Repeated child elements treated as records"),
        ("Syslog", "Semi-structured", ".log", "RFC 3164 and ISO 8601 syslog variants"),
        (
            "KV",
            "Semi-structured",
            ".log / .txt",
            "Key=value or key:value pairs, auto-detected",
        ),
        (
            "Text",
            "Unstructured",
            ".txt / .log",
            "Regex extraction of timestamps, severity, params",
        ),
        ("Parquet", "Binary", ".parquet", "Apache Parquet columnar format via pandas"),
    ]
    fmt_df = pd.DataFrame(
        fmt_info, columns=["Format", "Category", "Extensions", "Notes"]
    )
    st.dataframe(fmt_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("### ✅ Acceptance Criteria")
    ac = [
        (
            "FR1",
            "Multi-format ingestion",
            "Parse at least 3 formats; ≥1 structured, semi, unstructured",
        ),
        (
            "FR2",
            "Field extraction",
            "Extract timestamp, tool_id, severity, raw_message from ≥90% of records",
        ),
        ("FR3", "Normalisation", "All records map to the standard 20-field schema"),
        (
            "FR4",
            "Database storage",
            "Parsed rows stored in SQLite; queryable via filters",
        ),
        (
            "FR5",
            "Dashboard",
            "Upload → table → filter → chart in <3s on standard hardware",
        ),
        (
            "FR6",
            "AI summaries",
            "LLM-generated summary and classification for selected entries",
        ),
        (
            "FR7",
            "Synthetic data",
            "5-format demo files generated in-app without real tool logs",
        ),
    ]
    ac_df = pd.DataFrame(ac, columns=["FR", "Requirement", "Acceptance Criterion"])
    st.dataframe(ac_df, width="stretch", hide_index=True)
