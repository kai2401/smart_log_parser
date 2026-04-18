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
import json
import streamlit.components.v1

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

/* Base Typography */
html, body, [class*="css"], .stMarkdown { font-family: 'Inter', sans-serif !important; }
.stApp { background-color: #0d1117; color: #c9d1d9; }

/* Headers */
h1, h2, h3, h4, h5, h6 { font-family: 'Inter', sans-serif !important; font-weight: 600 !important; color: #e6edf3; letter-spacing: -0.01em; }
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
[data-testid="metric-container"] label { color: #8b949e !important; font-size: 0.8rem !important; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
[data-testid="stMetricValue"] { color: #58a6ff !important; font-family: 'JetBrains Mono', monospace !important; font-size: 2.2rem !important; font-weight: 600; }

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
[aria-selected="true"][data-baseweb="tab"] { background: #161b22 !important; color: #e6edf3 !important; border-bottom: 2px solid #58a6ff !important; }

/* File uploader */
[data-testid="stFileUploader"] {
    border: 1px dashed #30363d;
    border-radius: 8px;
    padding: 16px;
    background: #0d1117;
}

/* Code/mono text */
code { font-family: 'JetBrains Mono', monospace !important; background: #161b22; padding: 3px 6px; border-radius: 4px; font-size: 0.85rem; color: #79c0ff; border: 1px solid #30363d; }

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
.stSelectbox > div > div:focus-within, .stTextInput > div > input:focus, [data-testid="stChatInput"]:focus-within {
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
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []


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
            files = generate_sample_files("synthetic/samples")
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
        st.session_state.chat_messages = []
        st.rerun()

    st.divider()
    
# ---------------------------------------------------------------------------
# Handle file upload
# ---------------------------------------------------------------------------

if uploaded_file:
    # Only process if this specific file upload hasn't been parsed yet
    if getattr(st.session_state, "last_uploaded_file_id", None) != uploaded_file.file_id:
        content = uploaded_file.read().decode("utf-8", errors="replace")
        filename = uploaded_file.name
        with st.spinner(f"Parsing `{filename}`..."):
            db.delete_by_filename(filename)
            entries, warnings = parse_log(content, filename)
            n = db.insert_entries(entries)
            if filename not in st.session_state.parsed_filenames:
                st.session_state.parsed_filenames.append(filename)
            st.session_state.last_filename = filename
            st.session_state.chat_messages = []  # Reset for new file
            st.session_state.last_uploaded_file_id = uploaded_file.file_id

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
                st.session_state.chat_messages = [] # clear chat on file switch
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
            "event_name", "parameter_name", "parameter_value",
            "unit", "wafer_id", "recipe_id", "step_number", "source_format", "normalized_message",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        def _style_severity(val):
            colors = {
                "CRITICAL": "#ff7b72", "ERROR": "#f78166",
                "WARNING": "#cda869", "INFO": "#58a6ff", "DEBUG": "#8b949e",
            }
            return f"color: {colors.get(str(val).upper(), '#c9d1d9')}"

        styled = df[display_cols].style.map(_style_severity, subset=["severity"])
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
                
                # Changed to px.line, reverted x to hour and y to count
                fig_time = px.line(
                    time_counts, x="hour", y="count", color="severity",
                    title="Log Volume Over Time (hourly)",
                    color_discrete_map=SEV_COLORS,
                    markers=True  # Adds dots to each data point for better visibility
                )
                
                # Reverted xaxis_title and yaxis_title to standard time-series layout
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

        # Sensor line chart (desaturated at rest, saturated on hover)
        sensor_df = df.dropna(subset=["parameter_value"]) if "parameter_value" in df.columns else pd.DataFrame()
        if not sensor_df.empty and "timestamp" in sensor_df.columns:
            sensor_df = sensor_df.copy()
            sensor_df["timestamp"] = pd.to_datetime(sensor_df["timestamp"], errors="coerce")
            sensor_df = sensor_df.dropna(subset=["timestamp"]).sort_values("timestamp")

            if not sensor_df.empty:
                params_available = sensor_df["parameter_name"].dropna().unique().tolist()
                chosen_param = st.selectbox("Sensor to plot", params_available)

                p_df = sensor_df[sensor_df["parameter_name"] == chosen_param].copy()
                tools_in_param = p_df["tool_id"].dropna().unique().tolist()

                SAT = ["#58a6ff","#3fb950","#e3b341","#bc8cff","#39d0d0","#ff7b72","#79c0ff","#d29922"]
                sat_map = {t: SAT[i % len(SAT)] for i, t in enumerate(tools_in_param)}

                fig_sensor = go.Figure()
                for tool in tools_in_param:
                    t_df = p_df[p_df["tool_id"] == tool].sort_values("timestamp")
                    fig_sensor.add_trace(go.Scatter(
                        x=t_df["timestamp"],
                        y=t_df["parameter_value"],
                        mode="lines+markers",
                        name=tool,
                        line=dict(color=sat_map[tool], width=2, shape="spline", smoothing=0.99),
                        marker=dict(color=sat_map[tool], size=5),
                        hovertemplate=(
                            f"<b>{tool}</b><br>"
                            "%{x|%Y-%m-%d %H:%M:%S}<br>"
                            f"{chosen_param}: %{{y}}<extra></extra>"
                        ),
                    ))

                # ── Animation frames ───────────────────────────────────────
                all_times = sorted(p_df["timestamp"].unique())
                frames, slider_steps = [], []
                for i, cutoff in enumerate(all_times):
                    frame_traces = []
                    for tool in tools_in_param:
                        t_df = p_df[(p_df["tool_id"] == tool) & (p_df["timestamp"] <= cutoff)]
                        frame_traces.append(go.Scatter(
                            x=t_df["timestamp"],
                            y=t_df["parameter_value"],
                            mode="lines+markers",
                            line=dict(color=sat_map[tool], width=2.5),
                            marker=dict(color=sat_map[tool], size=6),
                        ))
                    frames.append(go.Frame(data=frame_traces, name=str(i)))
                    slider_steps.append(dict(
                        args=[[str(i)], {"frame": {"duration": 60, "redraw": True}, "mode": "immediate"}],
                        label="", method="animate",
                    ))
                fig_sensor.frames = frames

                fig_sensor.update_layout(
                    paper_bgcolor="#0d1117",
                    plot_bgcolor="#0d1117",
                    font_color="#c9d1d9",
                    legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
                    xaxis=dict(gridcolor="#1e2730", zeroline=False, title="Time"),
                    yaxis=dict(gridcolor="#1e2730", zeroline=False, title=chosen_param),
                    title=dict(
                        text=f"{chosen_param.capitalize()} Readings over Time",
                        font=dict(size=15, color="#e6edf3"),
                    ),
                    # Native Plotly hover line — draws a vertical rule across all traces
                    hovermode="x unified",
                    # This is the native Plotly feature that dims non-hovered traces
                    hoverdistance=30,
                    margin=dict(t=80, b=60),
                    updatemenus=[dict(
                        type="buttons",
                        showactive=False,
                        x=0.05, y=1.08,
                        xanchor="left", yanchor="top",
                        bgcolor="#21262d",
                        bordercolor="#30363d",
                        font=dict(color="#c9d1d9", size=12),
                        buttons=[
                            dict(
                                label="▶  Play",
                                method="animate",
                                args=[None, {
                                    "frame":       {"duration": 60, "redraw": True},
                                    "transition":  {"duration": 40, "easing": "linear"},
                                    "fromcurrent": True,
                                    "mode":        "immediate",
                                }],
                            ),
                            dict(
                                label="⏸  Pause",
                                method="animate",
                                args=[[None], {
                                    "frame":      {"duration": 0, "redraw": False},
                                    "mode":       "immediate",
                                    "transition": {"duration": 0},
                                }],
                            ),
                        ],
                    )],
                    sliders=[dict(
                        steps=slider_steps,
                        active=0,
                        x=0.0, y=0, len=1.0,
                        bgcolor="#161b22",
                        bordercolor="#30363d",
                        tickcolor="#30363d",
                        font=dict(color="#8b949e", size=10),
                        currentvalue=dict(visible=False),
                        transition=dict(duration=0),
                    )],
                )

                st.plotly_chart(fig_sensor, use_container_width=True,
                                key=f"sensor_{chosen_param.replace(' ','_')}")
# ─────────────────────── TAB 3: AI Insights ────────────────────────────────
with tab3:
    if not config.OPENAI_API_KEY:
        st.warning("⚠️ OpenAI API key must be set in the .env file in the project root to enable AI features.")
    elif df.empty:
        st.info("Upload logs first to chat with your data.")
    else:
        st.markdown("### 🤖 Chat with Your Log Data")
        st.caption("Ask questions about the active log file, its anomalies, tool performance, and errors.")

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
            if stats.get('errors', 0) > 0:
                suggestions.append(f"What might be causing the {stats['errors']} errors?")
            elif stats.get('warnings', 0) > 0:
                suggestions.append(f"Highlight the {stats['warnings']} warnings present.")
                
            if stats.get('alarms', 0) > 0:
                suggestions.append("Detail the alarms and their potential root causes.")
            if stats.get('tools', 0) > 1:
                suggestions.append("Compare the performance across different tools.")
            
            cols = st.columns(min(len(suggestions), 4))
            for i, sug in enumerate(suggestions[:4]):
                if cols[i].button(sug, key=f"sug_{i}", use_container_width=True):
                    st.session_state.chat_messages.append({"role": "user", "content": sug})
                    st.rerun()

        if chat_prompt:
            st.session_state.chat_messages.append({"role": "user", "content": chat_prompt})
            st.rerun()

        # If the last message is from the user, generate the assistant's response
        if st.session_state.chat_messages and st.session_state.chat_messages[-1]["role"] == "user":
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                message_placeholder.markdown(
                    '<div class="typing-indicator"><span></span><span></span><span></span></div>', 
                    unsafe_allow_html=True
                )
                
                # Give LLM a sample of the data (up to 30 rows) to keep token size in check
                sample_rows = df.head(30).to_dict(orient="records")
                response = analyzer.chat_with_logs(st.session_state.chat_messages, stats, sample_rows)
                
                message_placeholder.markdown(response)
                    
            # Add assistant response to chat history
            st.session_state.chat_messages.append({"role": "assistant", "content": response})
            st.rerun()

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
        ("recipe_id",           "TEXT",  "Optional",   "Process recipe identifier"),
        ("wafer_id",            "TEXT",  "Optional",   "Wafer / lot identifier"),
        ("process_stage",       "TEXT",  "Optional",   "LOAD | PROCESS | VENT | UNLOAD etc."),
        ("step_number",         "INTEGER", "Optional", "Process step or stage number"),
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
