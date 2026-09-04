"""Seed glossary_terms from ad_glossary CSV (BOM-safe)."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from rag.config import get_settings
from rag.db.models import GlossaryTerm
from rag.glossary.csv_io import parse_glossary_csv


def upsert_glossary(session: Session, rows: list[dict]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for row in rows:
        existing = session.get(GlossaryTerm, row["id"])
        if existing is None:
            by_std = session.execute(
                select(GlossaryTerm).where(GlossaryTerm.standard_term == row["standard_term"])
            ).scalar_one_or_none()
            if by_std is not None:
                existing = by_std
        if existing is None:
            session.add(GlossaryTerm(**row))
            inserted += 1
        else:
            existing.standard_term = row["standard_term"]
            existing.synonyms = row["synonyms"]
            existing.category = row["category"]
            existing.definition = row["definition"]
            existing.enabled = row["enabled"]
            updated += 1
    session.commit()
    return inserted, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed glossary_terms from CSV")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default="ad_glossary_v1.0_20260828.csv",
        type=Path,
    )
    args = parser.parse_args()
    path = args.csv_path
    if not path.exists():
        raise SystemExit(f"CSV not found: {path}")

    rows = parse_glossary_csv(path)
    settings = get_settings()
    sync_url = settings.database_url.replace("+asyncpg", "")
    engine = create_engine(sync_url, pool_pre_ping=True)
    with Session(engine) as session:
        inserted, updated = upsert_glossary(session, rows)
    print(f"seeded glossary: inserted={inserted} updated={updated} total_rows={len(rows)}")


if __name__ == "__main__":
    main()
