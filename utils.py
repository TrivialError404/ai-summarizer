import logging
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Persistence helpers
# ──────────────────────────────────────────────

def save_json(data: list[dict], path: str | Path) -> None:
    """
    Saves a list of dicts to a JSON file, creating parent directories as needed.

    Args:
        data: List of serialisable dicts.
        path: Target file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(data)} record(s) to {path.resolve()}")


def load_json(path: Path) -> list[dict]:
    """
    Loads a JSON file as a list of dicts.

    Args:
        path: Source file path.

    Returns:
        Parsed list of dicts.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def timestamp_iso_8601_to_str(timestamp):
    dt = datetime.fromisoformat(timestamp)
    return dt.strftime("%A %d.%m.%Y %H:%M")