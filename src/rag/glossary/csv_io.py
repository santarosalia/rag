"""Parse ad_glossary-style CSV (utf-8-sig / BOM safe)."""

from __future__ import annotations

import csv
from pathlib import Path


def parse_glossary_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            term_id = (raw.get("term_id") or "").strip()
            standard = (raw.get("standard_term") or "").strip()
            if not term_id or not standard:
                continue
            synonyms = [
                s.strip()
                for s in (raw.get("synonyms") or "").split("|")
                if s.strip() and s.strip() != standard
            ]
            seen: set[str] = set()
            uniq: list[str] = []
            for s in synonyms:
                if s not in seen:
                    seen.add(s)
                    uniq.append(s)
            rows.append(
                {
                    "id": term_id,
                    "standard_term": standard,
                    "synonyms": uniq,
                    "category": (raw.get("category") or "").strip() or None,
                    "definition": (raw.get("definition") or "").strip() or None,
                    "enabled": True,
                }
            )
    return rows
