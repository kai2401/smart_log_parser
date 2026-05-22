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


def _compute_unmapped(columns: list[str], mapping: dict[str, str]) -> list[str]:
    """
    Columns that are neither in the AI mapping nor covered by hardcoded aliases.
    These are the ones that truly fell through to raw metadata.
    """
    mapped_keys = set(mapping.keys()) | {k.lower() for k in mapping.keys()}
    return [
        col for col in columns
        if col not in mapped_keys
        and col.lower().strip() not in _ALL_ALIASES
    ]


def get_or_infer_mapping(
    columns: list[str], filename: str = ""
) -> tuple[dict[str, str], bool, list[str]]:
    """
    Return (mapping, was_cache_hit, unmapped_columns).

    mapping:          {raw_column -> canonical_field}
    was_cache_hit:    True when the result was served from DB cache
    unmapped_columns: columns not in mapping and not covered by hardcoded aliases
    """
    if not columns:
        return {}, False, []

    if not _api_key_available():
        return {}, False, []

    fingerprint = db._make_fingerprint(columns)

    # Cache hit
    cached = db.get_header_mapping(fingerprint)
    if cached is not None:
        logger.debug(f"Header mapping cache hit for fingerprint {fingerprint[:8]}...")
        return cached, True, _compute_unmapped(columns, cached)

    # All columns already known — skip LLM
    lower_cols = {c.lower().strip() for c in columns}
    if lower_cols.issubset(_ALL_ALIASES):
        logger.debug("All columns covered by hardcoded aliases — skipping LLM inference")
        return {}, False, []

    # Cache miss — call LLM
    logger.debug(f"Header mapping cache miss for {len(columns)} columns — calling LLM")
    mapping = analyzer.infer_column_mapping(columns)

    if mapping:
        db.save_header_mapping(fingerprint, mapping, filename)
        logger.debug(f"Inferred and cached {len(mapping)} column mappings for {filename!r}")

    return mapping, False, _compute_unmapped(columns, mapping)
