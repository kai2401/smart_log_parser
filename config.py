import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# OpenAI configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

DB_PATH = "tool_logs.db"

# LLM settings
LLM_MAX_TOKENS      = 1024
LLM_BATCH_SIZE      = 10   # rows sent to LLM per batch-analysis call
LLM_TIMEOUT_SECONDS = 30

# Severity order (higher = worse)
SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
