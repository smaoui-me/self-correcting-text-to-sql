"""Load configuration explicitly; importing this module never calls Groq."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def configure_console() -> None:
    """Windows consoles and redirected streams may default to legacy encodings."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Settings:
    database_path: Path
    model: str = "llama-3.1-8b-instant"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        path = Path(os.getenv("DATABASE_PATH", "chinook.db"))
        return cls(path if path.is_absolute() else ROOT / path,
                   os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))


def create_llm(settings: Settings):
    from langchain_groq import ChatGroq

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key or key == "your_groq_api_key_here":
        raise ValueError("Set GROQ_API_KEY in .env before running a live query.")
    return ChatGroq(model=settings.model, api_key=key, temperature=0,
                    timeout=30, max_retries=2, max_tokens=2048)
