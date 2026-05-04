from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


@dataclass(frozen=True)
class Settings:
    restaurant_name: str
    timezone: str
    database_path: Path
    open_time: str
    close_time: str
    slot_minutes: int
    slot_capacity: int
    openai_api_key: str | None
    openai_model: str


def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    return Settings(
        restaurant_name=os.getenv("RESTAURANT_NAME", "Juniper Table"),
        timezone=os.getenv("RESTAURANT_TIMEZONE", "America/New_York"),
        database_path=Path(os.getenv("DATABASE_PATH", project_root / "data" / "reservations.sqlite3")),
        open_time=os.getenv("RESTAURANT_OPEN_TIME", "17:00"),
        close_time=os.getenv("RESTAURANT_CLOSE_TIME", "22:00"),
        slot_minutes=int(os.getenv("RESERVATION_SLOT_MINUTES", "15")),
        slot_capacity=int(os.getenv("RESERVATION_SLOT_CAPACITY", "30")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    )
