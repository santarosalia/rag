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
    surfaces_by_length: list[str] = field(default_factory=list)
    # surface → canonical standard_term (for definition lookup)
    surface_to_standard: dict[str, str] = field(default_factory=dict)
    # standard_term → definition text
    definitions: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        self.surfaces.clear()
        self.surfaces_by_length.clear()
        self.surface_to_standard.clear()
        self.definitions.clear()

    def load_rows(self, rows: list[GlossaryTerm]) -> int:
        self.clear()
        for term in rows:
            if not term.enabled:
                continue
            standard = (term.standard_term or "").strip()
            if not standard:
                continue
            aliases = {standard, *(term.synonyms or [])}
            aliases = {a.strip() for a in aliases if a and a.strip()}
            frozen = frozenset(aliases)
            if term.definition and term.definition.strip():
                self.definitions[standard] = term.definition.strip()
            for surface in frozen:
                existing = self.surfaces.get(surface)
                if existing is None:
                    self.surfaces[surface] = frozen
                else:
                    self.surfaces[surface] = frozenset(existing | frozen)
                # prefer keeping an existing standard if surface already mapped
                self.surface_to_standard.setdefault(surface, standard)
        self.surfaces_by_length = sorted(self.surfaces.keys(), key=len, reverse=True)
        return len(self.surfaces)

    def aliases_for(self, surface: str) -> frozenset[str] | None:
        return self.surfaces.get(surface)

    def definition_for_surface(self, surface: str) -> tuple[str, str] | None:
        standard = self.surface_to_standard.get(surface)
        if not standard:
            return None
        definition = self.definitions.get(standard)
        if not definition:
            return None
        return standard, definition


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
