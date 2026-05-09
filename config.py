import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def get_api_key() -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "Variable GROQ_API_KEY absente. Copiez .env.example vers .env et renseignez la clé."
        )
    return key


def leads_path() -> Path:
    return ROOT / "leads.csv"
