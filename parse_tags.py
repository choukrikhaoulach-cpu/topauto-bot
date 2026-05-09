from __future__ import annotations

import re


def split_model_reply(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return "", "RIEN"
    sep = raw.rfind("|||")
    if sep < 0:
        return raw, "RIEN"
    visible = raw[:sep].strip()
    tag = raw[sep + 3 :].strip()
    visible = re.sub(r"\|\|\|[\s\S]*", "", visible).strip()
    return visible or raw[:sep].strip(), tag or "RIEN"


def extract_lead_nom_tel(tag: str) -> tuple[str, str] | None:
    t = tag.strip()
    if not re.match(r"^LEAD\b", t, re.IGNORECASE):
        return None
    body = re.sub(r"^LEAD\s*:?", "", t, flags=re.IGNORECASE).strip()
    nom = ""
    tel = ""
    if "|" in body:
        for part in body.split("|"):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k_norm = k.strip().lower()
            v = v.strip()
            if k_norm in ("nom", "name", "prenom"):
                nom = v
            if k_norm in ("tel", "telephone", "phone", "gsm"):
                tel = v
    else:
        chunks = [c.strip() for c in body.split(":") if c.strip()]
        if len(chunks) >= 2 and "=" not in body:
            nom, tel = chunks[0], chunks[1]
    if nom and tel:
        return nom, tel
    return None
