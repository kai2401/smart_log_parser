import sqlite3
import pandas as pd

conn = sqlite3.connect("tool_logs.db")
df = pd.read_sql(
    "SELECT timestamp, tool_id, source_format, source_filename, metadata FROM log_entries WHERE source_filename LIKE 'mqtt_%' ORDER BY timestamp DESC LIMIT 10",
    conn,
)
print(df.to_string())
