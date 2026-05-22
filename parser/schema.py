from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
import uuid


@dataclass
class LogEntry:
    """Canonical normalized log record stored in the database."""

    # --- identity ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- required core fields (best-effort defaults prevent crashes) ---
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    tool_id: str = "UNKNOWN"
    log_type: Optional[str] = None
    severity: str = "INFO"  # DEBUG | INFO | WARNING | ERROR | CRITICAL
    raw_message: str = ""
    drain_cluster_id: Optional[int] = None

    # --- dynamic schema overflow ---
    metadata: str = "{}"

    # --- source ---
    source_format: Optional[str] = (
        None  # json | csv | xml | syslog | text | kv | llm_parsed | universal
    )
    source_filename: Optional[str] = None

    # --- LLM outputs (populated after analysis) ---
    ai_summary: Optional[str] = None
    ai_classification: Optional[str] = None  # normal | warning | anomaly | fault
    ai_root_cause_hint: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def mandatory_fields() -> list[str]:
        """Fields that MUST be present for a valid record."""
        return ["timestamp", "tool_id", "severity", "raw_message"]

    def is_valid(self) -> tuple[bool, list[str]]:
        missing = [f for f in self.mandatory_fields() if not getattr(self, f)]
        return len(missing) == 0, missing


@dataclass
class RecipeEntry:
    """Process recipe / setpoint record — stored separately from log events."""

    # --- identity ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- timing ---
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # --- equipment ---
    tool_id: str = "UNKNOWN"

    # --- dynamic schema overflow ---
    metadata: str = "{}"

    # --- metadata ---
    raw_message: str = ""
    source_format: Optional[str] = None
    source_filename: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def mandatory_fields() -> list[str]:
        return ["timestamp", "tool_id"]

    def is_valid(self) -> tuple[bool, list[str]]:
        missing = [f for f in self.mandatory_fields() if not getattr(self, f)]
        return len(missing) == 0, missing
