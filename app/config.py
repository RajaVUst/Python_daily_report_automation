"""Central configuration: environment (.env) for secrets, YAML for business config."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", BASE_DIR / "config" / "config.yaml"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
APP_DB_URL = os.getenv("APP_DB_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


def resolve(path: str | os.PathLike) -> Path:
    """Resolve a config-relative path against the project root."""
    p = Path(path)
    return p if p.is_absolute() else BASE_DIR / p


def load_config() -> dict:
    """Read the YAML config fresh each time so edits apply to the next run."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("timezone", "UTC")
    cfg.setdefault("job", {}).setdefault("name", "daily_recon")
    cfg["job"].setdefault("cron", "0 7 * * *")
    cfg.setdefault("source", {"type": "sqlite"})
    cfg.setdefault("queries", [])
    cfg.setdefault("checks", [])
    cfg.setdefault("llm", {})
    cfg.setdefault("email", {})
    return cfg
