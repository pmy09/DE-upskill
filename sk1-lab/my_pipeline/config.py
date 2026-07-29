"""
ShopStream pipeline configuration and logging setup.
"""

from pathlib import Path
import logging

# Project root = directory containing this file (my_pipeline/)
BASE_DIR = Path(__file__).resolve().parent

CONFIG = {
    "input_dir": BASE_DIR / "data" / "raw",
    "output_dir": BASE_DIR / "data" / "processed",
    "log_dir": BASE_DIR / "logs",
    "crm_api_url": "https://api.shopstream.example.com/v2/customers",
    "crm_api_key": "sk-xxxx",  # Use environment variable in production
    "valid_regions": ["US", "EU", "APAC"],
    "email_regex": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "quality_threshold": 0.95,  # 95% of records must pass each check
    "source_priority": {"crm": 1, "website": 2, "erp": 3, "marketing": 4},
}

for d in [CONFIG["input_dir"], CONFIG["output_dir"], CONFIG["log_dir"]]:
    d.mkdir(parents=True, exist_ok=True)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_log_file = CONFIG["log_dir"] / "pipeline.log"

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=[
        logging.FileHandler(_log_file),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("shopstream")
