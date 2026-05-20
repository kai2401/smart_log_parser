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
    log_type: Optional[str] = (
        None  # process_step | alarm | sensor_reading | maintenance | info
    )
    severity: str = "INFO"  # DEBUG | INFO | WARNING | ERROR | CRITICAL

    # --- event ---
    event_name: Optional[str] = None

    # --- process context ---
    recipe_id: Optional[str] = None
    wafer_id: Optional[str] = None
    process_stage: Optional[str] = None
    step_number: Optional[int] = None

    # --- sensor / parameter ---
    parameter_name: Optional[str] = None
    parameter_value: Optional[float] = None
    unit: Optional[str] = None

    # --- messages ---
    raw_message: str = ""
    normalized_message: Optional[str] = None
    drain_cluster_id: Optional[int] = None

    # --- source ---
    source_format: Optional[str] = None  # json | csv | xml | syslog | text | kv
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

    # --- recipe specifics ---
    recipe_id: str = "UNKNOWN"
    recipe_name: Optional[str] = None
    step_number: Optional[int] = None
    setpoint_name: str = "UNKNOWN"
    setpoint_value: float = 0.0
    unit: Optional[str] = None

    # --- metadata ---
    raw_message: str = ""
    source_format: Optional[str] = None
    source_filename: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def mandatory_fields() -> list[str]:
        return ["timestamp", "tool_id", "recipe_id"]

    def is_valid(self) -> tuple[bool, list[str]]:
        missing = [f for f in self.mandatory_fields() if not getattr(self, f)]
        return len(missing) == 0, missing
