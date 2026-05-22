# ⚙️ Smart Tool Log Parser

A semiconductor equipment log intelligence platform that ingests heterogeneous raw tool logs, normalises them into a structured schema, stores them in SQLite, and uses Claude AI to explain alarms and anomalies.

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the dashboard
```bash
streamlit run app.py
```

### 3. Start MQTT Daemon (for live streaming)
```bash
python mqtt_server.py
```

### 4. Generate demo logs (optional — also available in-app)
```bash
python synthetic/generator.py
```

---

## 📡 Real-Time MQTT & Advanced Features

- **Live Edge Ingestion**: Run `mqtt_client.py` on edge devices (like a Raspberry Pi) to stream simulated fab machine logs directly to the platform over MQTT.
- **Daemon Processing**: `mqtt_server.py` runs as a background daemon, actively listening to the broker, parsing JSON payloads, and committing them to the database in real-time.
- **Live View Dashboard**: A dedicated tab in the Streamlit app uses `streamlit-autorefresh` to poll the database every 2 seconds, providing an instant view of incoming machine telemetry and alarms.
- **Drain3 Log Clustering**: Automatically masks highly entropic variables (e.g., sensor floats, IP addresses) in unstructured log messages, grouping similar events into static templates.
- **Background Batch Workers**: Massive multi-file batch uploads are offloaded to `threading.Thread` workers, preventing UI lockups and enabling real-time progress bars.

---

## 🔄 System Pipeline

```
Raw Tool Logs (JSON | CSV | XML | Syslog | Text)
        ↓
  Format Detection  (detector.py)
        ↓
  Format Parser     (parsers/*.py)
        ↓
  Field Extraction + Normalisation  (normalizer.py)
        ↓
  Canonical Schema  (schema.py → LogEntry)
        ↓
  SQLite Storage    (database/db.py)
        ↓
  Dashboard Display (app.py → Streamlit)
        ↓
  LLM Analysis      (llm/analyzer.py → Claude)
```

---

## 🤖 AI Features

- **Session Overview**: executive summary of the uploaded log session
- **Batch Classification**: classify up to 50 entries at once (normal / warning / anomaly / fault)
- **Deep-Dive Analysis**: detailed explanation + root cause + recommended action for any single entry
- **Dynamic Header Inference**: ingestion of different header names with same semantic meaning. Allowing for smoother integration.

Set your `ANTHROPIC_API_KEY` environment variable or paste it in the sidebar.

---

## 📐 Normalised Schema

| Field | Required | Description |
|---|---|---|
| id | Auto | UUID |
| timestamp | ✅ | ISO-8601 |
| tool_id | ✅ | Equipment identifier |
| severity | ✅ | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| raw_message | ✅ | Original log line |
| log_type | Auto | alarm / sensor_reading / process_step / maintenance / info |
| event_name | Optional | Human-readable event |
| alarm_code | Optional | Vendor fault code |
| recipe_id | Optional | Process recipe |
| wafer_id | Optional | Wafer / lot ID |
| parameter_name | Optional | Normalised sensor name |
| parameter_value | Optional | Numeric reading |
| unit | Optional | °C / mTorr / sccm etc. |
| ai_summary | LLM | Plain English explanation |
| ai_classification | LLM | normal / warning / anomaly / fault |
| ai_root_cause_hint | LLM | Troubleshooting suggestion |

---

## 📁 Project Structure

```
smart_log_parser/
├── app.py                        # Streamlit dashboard (main entry point)
├── mqtt_server.py                # Background MQTT listener & database committer
├── mqtt_client.py                # Fab machine MQTT payload simulator (Edge)
├── worker.py                     # Threaded background processing for batch uploads
├── config.py                     # Config: API keys, DB path, constants
├── requirements.txt
│
├── parser/
│   ├── __init__.py               # Pipeline orchestrator: detect → parse → normalise
│   ├── detector.py               # Format auto-detection (extension + content sniff)
│   ├── normalizer.py             # Field alias maps + value normalisation
│   ├── drain_manager.py          # Drain3 clustering template engine
│   ├── schema.py                 # LogEntry dataclass (canonical schema)
│   └── parsers/
│       ├── json_parser.py        # JSON / NDJSON
│       ├── csv_parser.py         # CSV / TSV
│       ├── xml_parser.py         # XML
│       ├── syslog_parser.py      # RFC 3164 + ISO syslog
│       └── text_parser.py        # Unstructured plain text (regex)
│
├── database/
│   └── db.py                     # SQLite CRUD, filters, summary stats
│
├── llm/
│   └── analyzer.py               # Anthropic Claude: batch classify, deep explain
│
└── synthetic/
    └── generator.py              # Generates realistic tool logs in all 5 formats
```

---

## 💻 Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11+ |
| Parsers | regex, stdlib csv/json/xml |
| Edge / Pipeline | paho-mqtt, drain3 |
| Database | SQLite (via stdlib sqlite3) |
| Dashboard | Streamlit, streamlit-autorefresh |
| LLM | Anthropic Claude (claude-sonnet-4) |
| Charts | Plotly |

---

## ✅ Acceptance Criteria

| FR | Requirement | Criterion |
|---|---|---|
| FR1 | Multi-format | ≥3 formats; structured + semi + unstructured |
| FR2 | Field extraction | ≥90% of records yield timestamp, tool_id, severity, raw_message |
| FR3 | Normalisation | All records map to the 20-field schema |
| FR4 | Storage | SQLite; queryable with filters |
| FR5 | Dashboard | Upload → table → filter → chart in <3s |
| FR6 | AI summaries | Summaries + classification for selected entries |
| FR7 | Synthetic data | 5-format demo files generated in-app |
