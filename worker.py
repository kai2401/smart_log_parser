"""
Background parsing worker for batch uploads.
"""

from __future__ import annotations

from threading import Thread

from parser import parse_log
from database import db


def _run_job(content_bytes: bytes, filename: str, job_id: str) -> None:
    try:
        db.update_job(job_id, status="PROCESSING", progress=5)
        entries, warnings = parse_log(content_bytes, filename)

        # Check if any entries came from LLM-assisted parsing
        # and need human review before committing
        has_llm_parsed = any(
            e.source_format == "llm_parsed" for e in entries
        )

        if has_llm_parsed and entries:
            # Stage records for human review instead of auto-committing
            raw_records = [e.to_dict() for e in entries]
            n = db.insert_pending_reviews(job_id, filename, raw_records)
            db.update_job(
                job_id,
                status="NEEDS_REVIEW",
                progress=100,
                total_records=n,
            )
        else:
            # Standard path: auto-commit to log_entries
            n = db.insert_entries(entries)
            db.update_job(
                job_id,
                status="COMPLETED",
                progress=100,
                total_records=n,
            )
    except Exception as exc:
        db.update_job(
            job_id,
            status="FAILED",
            progress=100,
            error_message=str(exc),
            total_records=0,
        )


def start_background_parsing(content_bytes: bytes, filename: str, job_id: str) -> None:
    thread = Thread(target=_run_job, args=(content_bytes, filename, job_id), daemon=True)
    thread.start()
