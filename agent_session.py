from __future__ import annotations

from pathlib import Path

from groq import Groq

from config import get_api_key
from leads_csv import append_lead_row
from parse_tags import extract_lead_nom_tel, split_model_reply
from prompts import load_system_prompt

MODEL_NAME = "llama-3.3-70b-versatile"
MAX_TOKENS = 900
TEMPERATURE = 0.35


class ConversationAgent:
    def __init__(self, leads_file: Path) -> None:
        self._client = Groq(api_key=get_api_key())
        self._system_prompt = load_system_prompt()
        self._history: list[dict[str, str]] = []
        self._leads_path = leads_file

    def reset(self) -> None:
        self._history.clear()

    def send_user_message(self, user_text: str) -> tuple[str, str, bool]:
        text = user_text.strip()
        if not text:
            return "", "RIEN", False

        self._history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": self._system_prompt}, *self._history]

        completion = self._client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

        raw = (completion.choices[0].message.content or "").strip()
        visible, tag = split_model_reply(raw)
        self._history.append({"role": "assistant", "content": visible})

        saved = False
        pair = extract_lead_nom_tel(tag)
        if pair:
            nom, tel = pair
            append_lead_row(self._leads_path, nom, tel, tag, visible)
            saved = True

        return visible, tag, saved
