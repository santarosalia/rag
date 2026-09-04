"""Glossary CRUD service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import GlossaryTerm
from rag.glossary.store import load_glossary_async


async def list_terms(
    session: AsyncSession,
    *,
    enabled: bool | None = None,
) -> list[GlossaryTerm]:
    stmt = select(GlossaryTerm).order_by(GlossaryTerm.id)
    if enabled is not None:
        stmt = stmt.where(GlossaryTerm.enabled.is_(enabled))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_term(session: AsyncSession, term_id: str) -> GlossaryTerm | None:
    return await session.get(GlossaryTerm, term_id)


async def create_term(
    session: AsyncSession,
    *,
    term_id: str,
    standard_term: str,
    synonyms: list[str] | None = None,
    category: str | None = None,
    definition: str | None = None,
    enabled: bool = True,
) -> GlossaryTerm:
    term = GlossaryTerm(
        id=term_id,
        standard_term=standard_term.strip(),
        synonyms=[s.strip() for s in (synonyms or []) if s.strip()],
        category=category,
        definition=definition,
        enabled=enabled,
    )
    session.add(term)
    await session.flush()
    await load_glossary_async(session)
    return term


async def update_term(
    session: AsyncSession,
    term: GlossaryTerm,
    *,
    standard_term: str | None = None,
    synonyms: list[str] | None = None,
    category: str | None = None,
    definition: str | None = None,
    enabled: bool | None = None,
) -> GlossaryTerm:
    if standard_term is not None:
        term.standard_term = standard_term.strip()
    if synonyms is not None:
        term.synonyms = [s.strip() for s in synonyms if s.strip()]
    if category is not None:
        term.category = category
    if definition is not None:
        term.definition = definition
    if enabled is not None:
        term.enabled = enabled
    await session.flush()
    await load_glossary_async(session)
    return term


async def delete_term(session: AsyncSession, term: GlossaryTerm) -> None:
    await session.delete(term)
    await session.flush()
    await load_glossary_async(session)
