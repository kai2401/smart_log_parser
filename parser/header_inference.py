"""
Header inference: maps unknown column names to canonical schema fields via LLM.
Results are cached in the DB so the LLM is never called twice for the same header set.
"""

import logging
import config
from database import db
from llm import analyzer
from parser.normalizer import (
    TIMESTAMP_ALIASES,
    TOOL_ID_ALIASES,
    SEVERITY_ALIASES,
    EVENT_NAME_ALIASES,
    RECIPE_ID_ALIASES,
    WAFER_ID_ALIASES,
    PROCESS_STAGE_ALIASES,
    PARAM_NAME_ALIASES,
    PARAM_VALUE_ALIASES,
    UNIT_ALIASES,
)

logger = logging.getLogger(__name__)

def _api_key_available() -> bool:
    return bool(config.OPENAI_API_KEY)


_ALL_ALIASES: set[str] = (
    TIMESTAMP_ALIASES
    | TOOL_ID_ALIASES
    | SEVERITY_ALIASES
    | EVENT_NAME_ALIASES
    | RECIPE_ID_ALIASES
    | WAFER_ID_ALIASES
    | PROCESS_STAGE_ALIASES
    | PARAM_NAME_ALIASES
    | PARAM_VALUE_ALIASES
    | UNIT_ALIASES
)


def get_or_infer_mapping(
    columns: list[str], filename: str = ""
) -> tuple[dict[str, str], bool]:
    """
    Return (mapping, was_cache_hit).

    mapping: {raw_column -> canonical_field}, empty dict means fall back to aliases.
    was_cache_hit: True when the result was served from DB cache.

    1. Return early if no API key.
    2. Compute fingerprint and check DB cache (returns True for cache hit).
    3. If all columns covered by hardcoded aliases, skip LLM.
    4. Call LLM on cache miss, persist non-empty result.
    """
    if not columns:
        return {}, False

    if not _api_key_available():
        return {}, False

    fingerprint = db._make_fingerprint(columns)

    # Cache hit — second element True so callers can distinguish hit from new inference
    cached = db.get_header_mapping(fingerprint)
    if cached is not None:
        logger.debug(f"Header mapping cache hit for fingerprint {fingerprint[:8]}...")
        return cached, True

    # All columns already known — skip LLM
    lower_cols = {c.lower().strip() for c in columns}
    if lower_cols.issubset(_ALL_ALIASES):
        logger.debug("All columns covered by hardcoded aliases — skipping LLM inference")
        return {}, False

    # Cache miss — call LLM
    logger.debug(f"Header mapping cache miss for {len(columns)} columns — calling LLM")
    mapping = analyzer.infer_column_mapping(columns)

    if mapping:
        db.save_header_mapping(fingerprint, mapping, filename)
        logger.debug(f"Inferred and cached {len(mapping)} column mappings for {filename!r}")

    return mapping, False
