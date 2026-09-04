"""In-memory glossary surfaces for Sparse synonym expansion (no Kiwi user dict)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from rag.db.models import GlossaryTerm
from rag.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GlossaryStore:
    """surface (standard or synonym) → full alias set including standard."""

    surfaces: dict[str, frozenset[str]] = field(default_factory=dict)
    # longest-first list for matching
    surfaces_by_length: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.surfaces.clear()
        self.surfaces_by_length.clear()

    def load_rows(self, rows: list[GlossaryTerm]) -> int:
        self.clear()
        for term in rows:
            if not term.enabled:
                continue
            aliases = {term.standard_term, *(term.synonyms or [])}
            aliases = {a.strip() for a in aliases if a and a.strip()}
            frozen = frozenset(aliases)
            for surface in frozen:
                # longer / later overwrite is fine; same alias set
                existing = self.surfaces.get(surface)
                if existing is None:
                    self.surfaces[surface] = frozen
                else:
                    self.surfaces[surface] = frozenset(existing | frozen)
        self.surfaces_by_length = sorted(self.surfaces.keys(), key=len, reverse=True)
        return len(self.surfaces)

    def aliases_for(self, surface: str) -> frozenset[str] | None:
        return self.surfaces.get(surface)


_store = GlossaryStore()


def get_glossary_store() -> GlossaryStore:
    return _store


def load_glossary_sync(session: Session) -> int:
    rows = session.execute(
        select(GlossaryTerm).where(GlossaryTerm.enabled.is_(True))
    ).scalars().all()
    n = _store.load_rows(list(rows))
    logger.info("glossary_store_loaded", surfaces=n, terms=len(rows))
    return n


async def load_glossary_async(session: AsyncSession) -> int:
    result = await session.execute(
        select(GlossaryTerm).where(GlossaryTerm.enabled.is_(True))
    )
    rows = list(result.scalars().all())
    n = _store.load_rows(rows)
    logger.info("glossary_store_loaded", surfaces=n, terms=len(rows))
    return n
