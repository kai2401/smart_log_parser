import logging
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# OpenAI configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

DB_PATH = "tool_logs.db"

# MQTT settings
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "fab/tool_logs")

# LLM settings
LLM_MAX_TOKENS = 1024
LLM_BATCH_SIZE = 10  # rows sent to LLM per batch-analysis call
LLM_TIMEOUT_SECONDS = 30

# Severity order (higher = worse)
SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

# Configure centralized logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("debug.log"), logging.StreamHandler(sys.stdout)],
)

# Silence watchdog to prevent infinite loops with Streamlit auto-reloader
logging.getLogger("watchdog").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.debug("Logging subsystem initialized.")
