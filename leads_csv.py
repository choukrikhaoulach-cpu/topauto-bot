from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


def append_lead_row(path: Path, nom: str, tel: str, tag: str, client_visible: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["horodatage_utc", "nom", "telephone", "tag_brut", "reponse_client"])
        w.writerow(
            [
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                nom,
                tel,
                tag,
                client_visible.replace("\n", " ").strip()[:800],
            ]
        )
