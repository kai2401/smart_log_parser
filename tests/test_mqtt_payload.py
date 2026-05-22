import json
from parser import parse_log

payload = json.dumps(
    [
        {
            "timestamp": "2024-03-01T08:00:00",
            "tool_id": "ETCH-01",
            "severity": "ERROR",
            "parameter_name": "temp",
            "parameter_value": 200,
        }
    ]
)
entries, _ = parse_log(payload.encode("utf-8"), "mqtt_ETCH-01.json")
print(entries[0].__dict__)
