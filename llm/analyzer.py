"""
LLM Analysis Layer — uses OpenAI Chat API to explain and classify log events.
"""

import json
import re
from pydantic import BaseModel
from openai import OpenAI
import config
import logging

logger = logging.getLogger(__name__)

# Configure OpenAI API key
client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

BATCH_SYSTEM = """You are an expert semiconductor equipment engineer and log analyst.
You will receive a batch of parsed tool log entries from semiconductor manufacturing equipment.

For each entry, respond with a JSON array where each element has:
  - "id": the entry id (copy exactly from input)
  - "summary": 1-2 sentence plain English explanation of what happened
  - "classification": one of: normal | warning | anomaly | fault
  - "root_cause_hint": brief possible cause or next troubleshooting step (or "" if normal)

Return ONLY the JSON array. No markdown fences, no preamble.
"""


def _call_chat(system: str, user: str, max_tokens: int) -> str:
    """Call the OpenAI chat completion endpoint and return the assistant content as text."""
    if not client:
        raise Exception(
            "OpenAI API key not configured. Please add it to your .env file."
        )
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        # Robust extraction of returned text
        content = ""
        try:
            content = response.choices[0].message.content
        except Exception:
            try:
                content = response.choices[
                    0
                ].message.content  # fallback for object-like responses
            except Exception:
                content = str(response)
        return content.strip()
    except Exception:
        logger.exception("OpenAI chat call failed")
        raise


def analyse_batch(entries: list[dict]) -> list[dict]:
    """
    Send up to LLM_BATCH_SIZE entries to OpenAI for explanation + classification.
    Returns list of dicts: {id, summary, classification, root_cause_hint}
    """
    if not entries:
        return []

    # Compact input to save tokens
    compact = []
    for e in entries:
        compact.append(
            {
                "id": e.get("id"),
                "tool_id": e.get("tool_id"),
                "severity": e.get("severity"),
                "log_type": e.get("log_type"),
                "event_name": e.get("event_name"),
                "parameter_name": e.get("parameter_name"),
                "parameter_value": e.get("parameter_value"),
                "unit": e.get("unit"),
                "normalized_message": e.get("normalized_message"),
            }
        )

    user_msg = json.dumps(compact, indent=2)

    try:
        raw = _call_chat(BATCH_SYSTEM, user_msg, max_tokens=config.LLM_MAX_TOKENS)
        # Strip any accidental fences
        raw = (
            raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        return json.loads(raw)
    except json.JSONDecodeError:
        return [
            {
                "id": e.get("id"),
                "summary": "Parse error",
                "classification": "normal",
                "root_cause_hint": "",
            }
            for e in entries
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Single-entry deep explanation (used in the AI Insights panel)
# ---------------------------------------------------------------------------

EXPLAIN_SYSTEM = """You are a semiconductor equipment specialist.
Given one parsed log entry, provide a detailed explanation for a process engineer.
Structure your response as:
**Event Summary**: (what happened in plain English)
**Possible Cause**: (most likely technical reason)
**Recommended Action**: (what the engineer should check or do next)
**Severity Assessment**: (how urgent is this)
Keep each section to 2-3 sentences.
"""


def explain_entry(entry: dict) -> str:
    """Return a markdown-formatted deep explanation of a single log entry."""
    user_msg = json.dumps(
        {
            k: v
            for k, v in entry.items()
            if k not in ("id", "ai_summary", "ai_classification", "ai_root_cause_hint")
            and v is not None
        },
        indent=2,
    )

    try:
        return _call_chat(EXPLAIN_SYSTEM, user_msg, max_tokens=600)
    except Exception as e:
        return f"⚠️ LLM unavailable: {e}"


# ---------------------------------------------------------------------------
# Overall log summary
# ---------------------------------------------------------------------------

OVERVIEW_SYSTEM = """You are a semiconductor manufacturing analyst.
Given summary statistics and a sample of log entries from a parsed log file,
write a concise 3-5 sentence executive summary for an engineering team.
Cover: overall health, notable alarms or anomalies, key machines involved, and one recommendation.
"""


def summarise_session(stats: dict, sample_entries: list[dict]) -> str:
    """Return a plain-text executive summary of the uploaded log session."""
    payload = {"stats": stats, "sample": sample_entries[:15]}
    try:
        return _call_chat(OVERVIEW_SYSTEM, json.dumps(payload), max_tokens=400)
    except Exception as e:
        return f"LLM summary unavailable: {e}"


INFER_COLUMNS_SYSTEM = """You are a data schema expert for semiconductor manufacturing log systems.
You will receive column names from an uploaded log file, and optionally up to 3 sample rows of data.
Map each column name to one of these canonical field names if there is a reasonable match.
Use both the column name AND the sample values to determine the best mapping.
Return ONLY a JSON object, no markdown, no explanation.

Canonical fields and their expected value patterns:
- timestamp: event time — e.g. "2024-03-01T08:00:52" (ISO 8601 datetime string)
  (aliases: ts, time, datetime, date, occurred_at, log_time)
- tool_id: equipment identifier — e.g. "ETCH-01", "CVD-03", "PVD-04" (tool type hyphen number)
  (aliases: machine, host, device, equip, unit)
- severity: log level — one of: INFO, WARNING, ERROR, CRITICAL
  (aliases: level, priority, sev, log_level, type)
- event_name: human-readable message — e.g. "Recipe started", "Alarm triggered: E002_PRESSURE_FAULT"
  (aliases: message, msg, description, text, detail)
- recipe_id: process recipe — e.g. "ETH_SiO2_v3", "CVD_TiN_v2", "PVD_Al_v1" (name_version format)
  (aliases: recipe, process, job)
- wafer_id: wafer or lot identifier — e.g. "LOT4225-W10", "LOT7414-W25" (LOT####-W## format)
  (aliases: wafer, lot, substrate, batch)
- parameter_name: sensor/metric name — e.g. "temperature", "pressure", "flow_rate", "rf_power", "chuck_temp"
  (aliases: sensor, metric, param, key)
- parameter_value: numeric sensor reading — e.g. 19.8818, 166.0908, 3.2709 (float, up to 4 decimal places)
  (aliases: value, reading, val, measurement)
- unit: unit of measurement — e.g. "°C", "mTorr", "sccm", "W", "Torr"
  (aliases: units, uom)
- process_stage: process phase — one of: LOAD, PUMP_DOWN, PROCESS, PURGE, VENT, UNLOAD, IDLE
  (aliases: stage, phase, step, operation)

Rules:
- Use sample row values as strong evidence — if a column's values look like timestamps, map it to timestamp even if the name is unusual
- Only map columns where you are confident (>80%)
- Unmapped columns should be omitted from the output entirely
- If a column clearly does not match any canonical field, omit it
- Return format: {"raw_column_name": "canonical_field_name", ...}"""

_CANONICAL_FIELDS = {
    "timestamp",
    "tool_id",
    "severity",
    "event_name",
    "recipe_id",
    "wafer_id",
    "parameter_name",
    "parameter_value",
    "unit",
    "process_stage",
}


def infer_column_mapping(
    columns: list[str], sample_rows: list[dict] | None = None
) -> dict[str, str]:
    """
    Use the LLM to map raw column names to canonical schema fields.
    Optionally accepts up to 3 sample rows to ground the inference on actual values.
    Returns an empty dict on any failure — callers must handle this gracefully.
    """
    if not columns:
        return {}
    try:
        if sample_rows:
            payload = {"columns": columns, "sample_rows": sample_rows[:3]}
        else:
            payload = {"columns": columns}
        user_msg = json.dumps(payload)
        raw = _call_chat(INFER_COLUMNS_SYSTEM, user_msg, max_tokens=300)
        raw = (
            raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        )
        result = json.loads(raw)
        if not isinstance(result, dict):
            return {}
        # Validate: discard entries with non-canonical values or non-string keys
        validated: dict[str, str] = {}
        seen_values: set[str] = set()
        for raw_col, canonical in result.items():
            if not isinstance(raw_col, str) or not isinstance(canonical, str):
                continue
            if canonical not in _CANONICAL_FIELDS:
                continue
            if canonical in seen_values:
                continue  # keep first, discard duplicates
            validated[raw_col] = canonical
            seen_values.add(canonical)
        return validated
    except Exception:
        logger.debug("infer_column_mapping failed — falling back to hardcoded aliases")
        return {}


def generate_text(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 600,
) -> str:
    """Generate freeform text for reports or summaries."""
    system_msg = system or "You are a semiconductor fab operations manager."
    try:
        return _call_chat(system_msg, prompt, max_tokens=max_tokens)
    except Exception as e:
        return f"⚠️ LLM unavailable: {e}"


# ---------------------------------------------------------------------------
# Conversational Chatbot (Guardrail Enforced)
# ---------------------------------------------------------------------------


class GuardedChatResponse(BaseModel):
    is_domain_relevant: bool
    rejection_reason: str | None
    assistant_reply: str


GUARDED_CHAT_SYSTEM = """
You are a highly capable AI assistant for a semiconductor data parsing platform.
A user has uploaded a log file. You are provided with statistics and a sample of the parsed log data
as context.

GUARDRAIL DIRECTIVES:
1. Domain Restriction: You must ONLY answer questions related to semiconductor manufacturing,
   equipment logs, systems analysis, or data parsing.
2. If the query falls outside this domain, set 'is_domain_relevant' to false, state the
   'rejection_reason', and leave 'assistant_reply' empty.
3. If the query is relevant, set 'is_domain_relevant' to true, leave 'rejection_reason' null,
   and provide your analysis in 'assistant_reply'. Format the reply using markdown.
"""


def _sanitize_input(text: str, max_length: int = 1500) -> str:
    """Strip control characters and truncate to mitigate buffer/context overflow injections."""
    sanitized = re.sub(r"[\x00-\x1F\x7F]", "", text)
    return sanitized[:max_length]


def chat_with_logs(
    messages: list[dict], stats: dict, sample_entries: list[dict]
) -> str:
    """Chat with the LLM using domain-enforced guardrails and sanitized context."""
    if not client:
        return "⚠️ OpenAI API key not configured. Please add it to your .env file."

    context_msg = (
        f"CONTEXT:\nStats: {json.dumps(stats)}"
        f"\nSample Data: {json.dumps(sample_entries[:20])}"
    )

    llm_messages = [
        {"role": "system", "content": GUARDED_CHAT_SYSTEM},
        {"role": "system", "content": context_msg},
    ]

    # Apply sanitization to the incoming user messages
    for msg in messages:
        if msg["role"] == "user":
            msg["content"] = _sanitize_input(msg["content"])
        llm_messages.append(msg)

    try:
        response = client.beta.chat.completions.parse(
            model=config.OPENAI_MODEL,
            messages=llm_messages,
            response_format=GuardedChatResponse,
            timeout=config.LLM_TIMEOUT_SECONDS,
        )

        parsed_output = response.choices[0].message.parsed

        if not parsed_output.is_domain_relevant:
            logger.warning(f"Guardrail triggered: {parsed_output.rejection_reason}")
            return f"⚠️ Query rejected: {parsed_output.rejection_reason}"

        return parsed_output.assistant_reply

    except Exception as e:
        logger.exception("OpenAI chat failed or guardrail error")
        return f"⚠️ System unavailable: {e}"
