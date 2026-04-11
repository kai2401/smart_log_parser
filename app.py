"""
Smart Tool Log Parser — Streamlit Dashboard
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import StringIO
import time

import config
from parser import parse_log
from database import db
from llm import analyzer
from synthetic.generator import generate_sample_files

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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

/* Base */
html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
.stApp { background-color: #0d0f14; color: #c9d1d9; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #10131a;
    border-right: 1px solid #1e2433;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: #141820;
    border: 1px solid #1e2433;
    border-radius: 8px;
    padding: 16px;
}
[data-testid="metric-container"] label { color: #8b949e !important; font-size: 0.75rem !important; letter-spacing: 0.08em; text-transform: uppercase; }
[data-testid="stMetricValue"] { color: #58a6ff !important; font-family: 'JetBrains Mono', monospace !important; font-size: 2rem !important; }

/* Dataframe */
[data-testid="stDataFrame"] { border: 1px solid #1e2433; border-radius: 6px; }

/* Buttons */
.stButton > button {
    background: #1e2d47;
    color: #58a6ff;
    border: 1px solid #1e4070;
    border-radius: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    transition: all 0.2s;
}
.stButton > button:hover { background: #233a5e; border-color: #58a6ff; }

/* Primary button */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1e4070, #0d2a4a);
    color: #79c0ff;
    border-color: #388bfd;
}

/* Tab styling */
[data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #1e2433 !important; }
[data-baseweb="tab"] {
    background: transparent;
    color: #8b949e;
    border-radius: 6px 6px 0 0;
    font-size: 0.85rem;
    letter-spacing: 0.04em;
}
[aria-selected="true"][data-baseweb="tab"] { background: #141820 !important; color: #58a6ff !important; border-bottom: 2px solid #58a6ff !important; }

/* File uploader */
[data-testid="stFileUploader"] {
    border: 1px dashed #1e4070;
    border-radius: 8px;
    padding: 12px;
    background: #0d1117;
}

/* Code/mono text */
code { font-family: 'JetBrains Mono', monospace; background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; color: #79c0ff; }

/* Headers */
h1, h2, h3 { font-family: 'Syne', sans-serif !important; }
h1 { font-weight: 800; letter-spacing: -0.02em; }

/* Alert boxes */
.stAlert { border-radius: 6px; }

/* Severity badges */
.badge-critical { color: #ff7b72; font-weight: 700; }
.badge-error    { color: #f78166; }
.badge-warning  { color: #cda869; }
.badge-info     { color: #58a6ff; }
.badge-debug    { color: #8b949e; }

/* AI panel */
.ai-panel {
    background: linear-gradient(135deg, #0d1829, #0d1a14);
    border: 1px solid #1e4070;
    border-radius: 10px;
    padding: 20px;
    margin-top: 12px;
}

/* Divider */
hr { border-color: #1e2433; }

/* Selectbox + input */
.stSelectbox > div > div, .stTextInput > div > input {
    background: #141820 !important;
    border-color: #1e2433 !important;
    color: #c9d1d9 !important;
}
</style>
""", unsafe_allow_html=True)

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
if "ai_session_summary" not in st.session_state:
    st.session_state.ai_session_summary = ""


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Smart Tool Log Parser")
    st.caption("Semiconductor Equipment Intelligence")
    st.divider()

    st.markdown("### 📁 Upload Log File")
    uploaded_file = st.file_uploader(
        "Supports JSON, CSV, XML, Syslog, Plain Text",
        type=["json", "csv", "xml", "log", "txt", "syslog"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("### 🧪 Demo Logs")
    if st.button("Generate Synthetic Logs", use_container_width=True):
        with st.spinner("Generating..."):
            files = generate_sample_files("synthetic/samples", n_each=60)
            st.session_state["demo_files"] = files
        st.success("✓ 5 format samples ready in sidebar")

    if "demo_files" in st.session_state:
        st.caption("Load a demo file:")
        for fmt, path in st.session_state["demo_files"].items():
            if st.button(f"  {fmt.upper()}", key=f"demo_{fmt}", use_container_width=True):
                with open(path, "rb") as f:
                    content = f.read().decode("utf-8", errors="replace")
                filename = os.path.basename(path)
                with st.spinner(f"Parsing {filename}..."):
                    db.delete_by_filename(filename)
                    entries, warnings = parse_log(content, filename)
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
    if st.button("Clear All Data", use_container_width=True):
        db.clear_all()
        st.session_state.parsed_filenames = []
        st.session_state.last_filename = None
        st.session_state.ai_session_summary = ""
        st.rerun()

    st.divider()
    
# ---------------------------------------------------------------------------
# Handle file upload
# ---------------------------------------------------------------------------

if uploaded_file:
    content = uploaded_file.read().decode("utf-8", errors="replace")
    filename = uploaded_file.name
    with st.spinner(f"Parsing `{filename}`..."):
        db.delete_by_filename(filename)
        entries, warnings = parse_log(content, filename)
        n = db.insert_entries(entries)
        if filename not in st.session_state.parsed_filenames:
            st.session_state.parsed_filenames.append(filename)
        st.session_state.last_filename = filename
        st.session_state.ai_session_summary = ""  # Reset for new file

    if n > 0:
        st.success(f"✅ Parsed and stored **{n}** log entries from `{filename}`")
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} parsing warnings"):
            for w in warnings:
                st.warning(w)

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
            selected_file = st.selectbox("Switch file", all_files, index=all_files.index(active_file))
            if selected_file != active_file:
                st.session_state.last_filename = selected_file
                active_file = selected_file

# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------

stats = db.get_summary_stats(active_file)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Entries", f"{stats['total']:,}")
c2.metric("Unique Tools",  stats['tools'])
c3.metric("🔴 Alarms",    stats['alarms'])
c4.metric("⚠️ Errors",    stats['errors'])
c5.metric("🟡 Warnings",  stats['warnings'])

st.divider()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

with st.expander("🔍 Filters", expanded=True):
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    all_tools = ["All"] + db.get_distinct_values("tool_id", active_file)
    all_sevs  = ["All"] + db.get_distinct_values("severity", active_file)
    all_types = ["All"] + db.get_distinct_values("log_type", active_file)
    all_fmts  = ["All"] + db.get_distinct_values("source_format", active_file)

    f_tool   = fc1.selectbox("Tool ID",    all_tools)
    f_sev    = fc2.selectbox("Severity",   all_sevs)
    f_type   = fc3.selectbox("Log Type",   all_types)
    f_fmt    = fc4.selectbox("Format",     all_fmts)
    f_search = fc5.text_input("🔎 Search", placeholder="alarm, wafer, recipe...")

    filter_kwargs = dict(
        tool_id  = None if f_tool  == "All" else f_tool,
        severity = None if f_sev   == "All" else f_sev,
        log_type = None if f_type  == "All" else f_type,
        source_filename = active_file,
        search   = f_search or None,
    )
    if f_fmt != "All":
        filter_kwargs["source_format"] = f_fmt  # extend query if needed

rows = db.query_entries(**filter_kwargs, limit=500)
df = pd.DataFrame(rows) if rows else pd.DataFrame()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Parsed Logs",
    "📊 Analytics",
    "🤖 AI Insights",
    "📖 Schema Reference",
])

# ─────────────────────── TAB 1: Parsed Logs ────────────────────────────────
with tab1:
    if df.empty:
        st.info("No data yet — upload a log file or load a demo log from the sidebar.")
    else:
        display_cols = [
            "timestamp", "tool_id", "severity", "log_type",
            "event_name", "alarm_code", "parameter_name", "parameter_value",
            "unit", "wafer_id", "recipe_id", "source_format", "normalized_message",
            "drain3_template",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        def _style_severity(val):
            colors = {
                "CRITICAL": "#ff7b72", "ERROR": "#f78166",
                "WARNING": "#cda869", "INFO": "#58a6ff", "DEBUG": "#8b949e",
            }
            return f"color: {colors.get(str(val).upper(), '#c9d1d9')}"

        # Show drain3 template as tooltip if present
        def _drain3_tooltip(val):
            if pd.isna(val) or not val:
                return ""
            return f"Template: {val}"
        styled = df[display_cols].style.map(_style_severity, subset=["severity"])
        if "drain3_template" in df.columns:
            styled = styled.format({"drain3_template": _drain3_tooltip})
        st.dataframe(styled, use_container_width=True, height=480)

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
                "CRITICAL": "#ff7b72", "ERROR": "#f78166",
                "WARNING": "#cda869", "INFO": "#58a6ff", "DEBUG": "#8b949e"
            }
            fig_sev = px.pie(
                sev_counts, names="severity", values="count",
                title="Log Severity Distribution",
                hole=0.5,
                color="severity",
                color_discrete_map=SEV_COLORS,
            )
            fig_sev.update_layout(
                paper_bgcolor="#0d0f14", plot_bgcolor="#0d0f14",
                font_color="#c9d1d9", legend_bgcolor="#0d0f14",
            )
            st.plotly_chart(fig_sev, use_container_width=True)

        # Log type breakdown (horizontal bar)
        with col_r:
            type_counts = df["log_type"].value_counts().reset_index()
            type_counts.columns = ["log_type", "count"]
            fig_type = px.bar(
                type_counts, x="count", y="log_type", orientation="h",
                title="Events by Log Type",
                color="count",
                color_continuous_scale=["#1e4070", "#58a6ff"],
            )
            fig_type.update_layout(
                paper_bgcolor="#0d0f14", plot_bgcolor="#141820",
                font_color="#c9d1d9", showlegend=False,
                yaxis=dict(autorange="reversed"),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_type, use_container_width=True)

        # Events over time
        if "timestamp" in df.columns:
            df_time = df.dropna(subset=["timestamp"]).copy()
            df_time["timestamp"] = pd.to_datetime(df_time["timestamp"], errors="coerce")
            df_time = df_time.dropna(subset=["timestamp"])
            if not df_time.empty:
                df_time["hour"] = df_time["timestamp"].dt.floor("h")
                time_counts = df_time.groupby(["hour", "severity"]).size().reset_index(name="count")
                fig_time = px.bar(
                    time_counts, x="hour", y="count", color="severity",
                    title="Log Volume Over Time (hourly)",
                    color_discrete_map=SEV_COLORS,
                )
                fig_time.update_layout(
                    paper_bgcolor="#0d0f14", plot_bgcolor="#141820",
                    font_color="#c9d1d9", legend_bgcolor="#0d0f14",
                    xaxis_title="Time", yaxis_title="Count",
                )
                st.plotly_chart(fig_time, use_container_width=True)

        # Alarms per tool
        alarm_df = df[df["log_type"] == "alarm"] if "log_type" in df.columns else pd.DataFrame()
        if not alarm_df.empty:
            tool_alarms = alarm_df["tool_id"].value_counts().reset_index()
            tool_alarms.columns = ["tool_id", "alarm_count"]
            fig_ta = px.bar(
                tool_alarms, x="tool_id", y="alarm_count",
                title="Alarms per Tool",
                color="alarm_count",
                color_continuous_scale=["#1e4070", "#ff7b72"],
            )
            fig_ta.update_layout(
                paper_bgcolor="#0d0f14", plot_bgcolor="#141820",
                font_color="#c9d1d9", coloraxis_showscale=False,
            )
            st.plotly_chart(fig_ta, use_container_width=True)

        # Sensor scatter (parameter value over time)
        sensor_df = df.dropna(subset=["parameter_value"]) if "parameter_value" in df.columns else pd.DataFrame()
        if not sensor_df.empty and "timestamp" in sensor_df.columns:
            sensor_df = sensor_df.copy()
            sensor_df["timestamp"] = pd.to_datetime(sensor_df["timestamp"], errors="coerce")
            sensor_df = sensor_df.dropna(subset=["timestamp"])
            if not sensor_df.empty:
                params_available = sensor_df["parameter_name"].dropna().unique().tolist()
                chosen_param = st.selectbox("Sensor to plot", params_available)
                p_df = sensor_df[sensor_df["parameter_name"] == chosen_param]
                fig_sensor = px.scatter(
                    p_df, x="timestamp", y="parameter_value", color="tool_id",
                    title=f"{chosen_param} readings over time",
                    hover_data=["severity", "alarm_code", "wafer_id"],
                )
                fig_sensor.update_layout(
                    paper_bgcolor="#0d0f14", plot_bgcolor="#141820",
                    font_color="#c9d1d9", legend_bgcolor="#0d0f14",
                )
                st.plotly_chart(fig_sensor, use_container_width=True)

# ─────────────────────── TAB 3: AI Insights ────────────────────────────────
with tab3:
    if not config.OPENAI_API_KEY:
        st.warning("⚠️ OpenAI API key must be set in the .env file in the project root to enable AI features.")
    elif df.empty:
        st.info("Upload logs first.")
    else:
        # Session summary
        st.markdown("### 📝 Session Overview")
        if st.button("Generate AI Overview", type="primary"):
            with st.spinner("Analysing log session..."):
                sample = df.head(20).to_dict(orient="records")
                summary = analyzer.summarise_session(stats, sample)
                st.session_state.ai_session_summary = summary
        if st.session_state.ai_session_summary:
            st.markdown(
                f'<div class="ai-panel">{st.session_state.ai_session_summary}</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # Batch classify
        st.markdown("### ⚡ Batch Classify Log Entries")
        n_batch = st.slider("Number of entries to classify", 5, 50, 10)
        if st.button("Run Batch AI Classification", type="primary"):
            sample_rows = df.head(n_batch).to_dict(orient="records")
            with st.spinner(f"Classifying {n_batch} entries with Claude..."):
                results = analyzer.analyse_batch(sample_rows)
                if results:
                    for r in results:
                        db.update_ai_fields(
                            r["id"],
                            r.get("summary", ""),
                            r.get("classification", ""),
                            r.get("root_cause_hint", ""),
                        )
                    st.success(f"✓ Classified {len(results)} entries")
                    st.rerun()
                else:
                    st.error("LLM returned no results. Check your .env OpenAI API key.")

        # Show AI-enriched results
        ai_rows = [r for r in rows if r.get("ai_summary")]
        if ai_rows:
            st.markdown("### 🧠 AI-Enriched Entries")
            for row in ai_rows[:20]:
                cls = row.get("ai_classification", "normal")
                cls_emoji = {"fault": "🔴", "anomaly": "🟠", "warning": "🟡", "normal": "🟢"}.get(cls, "⚪")
                with st.expander(
                    f"{cls_emoji} [{row.get('tool_id','?')}] {row.get('event_name','') or row.get('normalized_message','')[:80]}"
                ):
                    col_a, col_b = st.columns([1, 2])
                    with col_a:
                        st.caption("**Classification**")
                        st.markdown(f"`{cls.upper()}`")
                        st.caption("**Severity**")
                        st.markdown(f"`{row.get('severity','')}`")
                        st.caption("**Tool**")
                        st.markdown(f"`{row.get('tool_id','')}`")
                        if row.get("alarm_code"):
                            st.caption("**Alarm Code**")
                            st.markdown(f"`{row['alarm_code']}`")
                    with col_b:
                        st.caption("**AI Summary**")
                        st.markdown(row.get("ai_summary", ""))
                        if row.get("ai_root_cause_hint"):
                            st.caption("**Root Cause Hint**")
                            st.info(row["ai_root_cause_hint"])

        st.divider()

        # Deep-dive single entry
        st.markdown("### 🔬 Deep-Dive Analysis")
        st.caption("Select a specific log entry for detailed AI explanation.")
        if not df.empty:
            row_labels = [
                f"[{r.get('tool_id','?')}] {str(r.get('timestamp',''))[:19]} — {r.get('event_name','') or r.get('normalized_message','')[:60]}"
                for r in rows[:50]
            ]
            selected_idx = st.selectbox("Choose entry", range(len(row_labels)), format_func=lambda i: row_labels[i])
            if st.button("Analyse Selected Entry", type="primary"):
                entry_data = rows[selected_idx]
                with st.spinner("Generating detailed analysis..."):
                    explanation = analyzer.explain_entry(entry_data)
                st.markdown(f'<div class="ai-panel">{explanation}</div>', unsafe_allow_html=True)

# ─────────────────────── TAB 4: Schema Reference ───────────────────────────
with tab4:
    st.markdown("### 📐 Normalised Log Schema")
    st.caption("Every log entry — regardless of source format — is mapped to this standard structure.")

    schema_info = [
        ("id",                  "TEXT",  "✅ Auto",    "Unique record UUID"),
        ("timestamp",           "TEXT",  "✅ Req",     "ISO-8601 event timestamp"),
        ("tool_id",             "TEXT",  "✅ Req",     "Equipment / machine identifier"),
        ("log_type",            "TEXT",  "Auto",       "process_step | alarm | sensor_reading | maintenance | info"),
        ("severity",            "TEXT",  "✅ Req",     "DEBUG | INFO | WARNING | ERROR | CRITICAL"),
        ("event_name",          "TEXT",  "Optional",   "Human-readable event description"),
        ("alarm_code",          "TEXT",  "Optional",   "Vendor alarm/fault code"),
        ("recipe_id",           "TEXT",  "Optional",   "Process recipe identifier"),
        ("wafer_id",            "TEXT",  "Optional",   "Wafer / lot identifier"),
        ("process_stage",       "TEXT",  "Optional",   "LOAD | PROCESS | VENT | UNLOAD etc."),
        ("parameter_name",      "TEXT",  "Optional",   "Normalised sensor/parameter name"),
        ("parameter_value",     "REAL",  "Optional",   "Numeric sensor reading"),
        ("unit",                "TEXT",  "Optional",   "Unit of measurement"),
        ("raw_message",         "TEXT",  "✅ Req",     "Original log line / message"),
        ("normalized_message",  "TEXT",  "Auto",       "Cleaned human-readable version"),
        ("source_format",       "TEXT",  "Auto",       "json | csv | xml | syslog | text"),
        ("source_filename",     "TEXT",  "Auto",       "Originating filename"),
        ("ai_summary",          "TEXT",  "LLM",        "AI-generated plain English summary"),
        ("ai_classification",   "TEXT",  "LLM",        "normal | warning | anomaly | fault"),
        ("ai_root_cause_hint",  "TEXT",  "LLM",        "Possible cause / troubleshooting hint"),
    ]

    schema_df = pd.DataFrame(schema_info, columns=["Field", "Type", "Status", "Description"])
    st.dataframe(schema_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🔄 Supported Input Formats")
    fmt_info = [
        ("JSON",   "Structured",       ".json",       "Array or newline-delimited JSON objects"),
        ("CSV",    "Structured",       ".csv / .tsv", "Header row required; comma or tab delimited"),
        ("XML",    "Structured",       ".xml",        "Repeated child elements treated as records"),
        ("Syslog", "Semi-structured",  ".log",        "RFC 3164 and ISO 8601 syslog variants"),
        ("Text",   "Unstructured",     ".txt / .log", "Regex extraction of timestamps, severity, params"),
    ]
    fmt_df = pd.DataFrame(fmt_info, columns=["Format", "Category", "Extensions", "Notes"])
    st.dataframe(fmt_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### ✅ Acceptance Criteria")
    ac = [
        ("FR1", "Multi-format ingestion",  "Parse at least 3 formats; ≥1 structured, semi, unstructured"),
        ("FR2", "Field extraction",         "Extract timestamp, tool_id, severity, raw_message from ≥90% of records"),
        ("FR3", "Normalisation",            "All records map to the standard 20-field schema"),
        ("FR4", "Database storage",         "Parsed rows stored in SQLite; queryable via filters"),
        ("FR5", "Dashboard",                "Upload → table → filter → chart in <3s on standard hardware"),
        ("FR6", "AI summaries",             "LLM-generated summary and classification for selected entries"),
        ("FR7", "Synthetic data",           "5-format demo files generated in-app without real tool logs"),
    ]
    ac_df = pd.DataFrame(ac, columns=["FR", "Requirement", "Acceptance Criterion"])
    st.dataframe(ac_df, use_container_width=True, hide_index=True)
