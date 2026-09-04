from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.session import get_db
from rag.glossary import service as glossary_service
from rag.glossary.store import load_glossary_async
from rag.models.schemas import (
    GlossaryCreate,
    GlossaryReloadResponse,
    GlossaryResponse,
    GlossaryUpdate,
)

router = APIRouter(prefix="/glossary")


def _to_response(term) -> GlossaryResponse:
    return GlossaryResponse(
        id=term.id,
        standard_term=term.standard_term,
        synonyms=list(term.synonyms or []),
        category=term.category,
        definition=term.definition,
        enabled=term.enabled,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


@router.get("", response_model=list[GlossaryResponse])
async def list_glossary(
    enabled: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[GlossaryResponse]:
    terms = await glossary_service.list_terms(db, enabled=enabled)
    return [_to_response(t) for t in terms]


@router.post("", response_model=GlossaryResponse, status_code=201)
async def create_glossary(
    body: GlossaryCreate,
    db: AsyncSession = Depends(get_db),
) -> GlossaryResponse:
    existing = await glossary_service.get_term(db, body.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Glossary term id already exists")
    try:
        term = await glossary_service.create_term(
            db,
            term_id=body.id,
            standard_term=body.standard_term,
            synonyms=body.synonyms,
            category=body.category,
            definition=body.definition,
            enabled=body.enabled,
        )
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="standard_term already exists") from e
    return _to_response(term)


@router.post("/reload", response_model=GlossaryReloadResponse)
async def reload_glossary(
    db: AsyncSession = Depends(get_db),
) -> GlossaryReloadResponse:
    surfaces = await load_glossary_async(db)
    return GlossaryReloadResponse(surfaces=surfaces)


@router.get("/{term_id}", response_model=GlossaryResponse)
async def get_glossary(
    term_id: str,
    db: AsyncSession = Depends(get_db),
) -> GlossaryResponse:
    term = await glossary_service.get_term(db, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return _to_response(term)


@router.patch("/{term_id}", response_model=GlossaryResponse)
async def patch_glossary(
    term_id: str,
    body: GlossaryUpdate,
    db: AsyncSession = Depends(get_db),
) -> GlossaryResponse:
    term = await glossary_service.get_term(db, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    try:
        term = await glossary_service.update_term(
            db,
            term,
            standard_term=body.standard_term,
            synonyms=body.synonyms,
            category=body.category,
            definition=body.definition,
            enabled=body.enabled,
        )
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="standard_term already exists") from e
    return _to_response(term)


@router.delete("/{term_id}", status_code=204)
async def delete_glossary(
    term_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    term = await glossary_service.get_term(db, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    await glossary_service.delete_term(db, term)
