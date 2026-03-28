"""
LLM Analysis Layer — uses OpenAI Chat API to explain and classify log events.
"""

import json
import time
import openai
import config
import logging

logger = logging.getLogger(__name__)

# Configure OpenAI API key
openai.api_key = config.OPENAI_API_KEY


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
    try:
        response = openai.ChatCompletion.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        # Robust extraction of returned text
        content = ""
        try:
            content = response["choices"][0]["message"]["content"]
        except Exception:
            try:
                content = response.choices[0].message.content  # fallback for object-like responses
            except Exception:
                content = str(response)
        return content.strip()
    except Exception as e:
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
        compact.append({
            "id":              e.get("id"),
            "tool_id":         e.get("tool_id"),
            "severity":        e.get("severity"),
            "log_type":        e.get("log_type"),
            "event_name":      e.get("event_name"),
            "alarm_code":      e.get("alarm_code"),
            "parameter_name":  e.get("parameter_name"),
            "parameter_value": e.get("parameter_value"),
            "unit":            e.get("unit"),
            "normalized_message": e.get("normalized_message"),
        })

    user_msg = json.dumps(compact, indent=2)

    try:
        raw = _call_chat(BATCH_SYSTEM, user_msg, max_tokens=config.LLM_MAX_TOKENS)
        # Strip any accidental fences
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return [{"id": e.get("id"), "summary": "Parse error", "classification": "normal", "root_cause_hint": ""} for e in entries]
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
    user_msg = json.dumps({
        k: v for k, v in entry.items()
        if k not in ("id", "ai_summary", "ai_classification", "ai_root_cause_hint")
        and v is not None
    }, indent=2)

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
