"""Sparse FTS query expansion B: longest surface match → alias OR tsquery."""

from __future__ import annotations

import re

from rag.glossary.store import GlossaryStore, get_glossary_store
from rag.indexing.morphology import KiwiMorphAnalyzer, get_morph_analyzer

_LEXEME_OK = re.compile(r"^[0-9A-Za-z가-힣]+$")


def sanitize_lexeme(token: str) -> str | None:
    form = token.strip()
    if not form or not _LEXEME_OK.match(form):
        return None
    return form


def morph_lexemes(text: str, morph: KiwiMorphAnalyzer) -> list[str]:
    analyzed = morph.analyze(text)
    if not analyzed.strip():
        analyzed = text
    out: list[str] = []
    seen: set[str] = set()
    for part in analyzed.split():
        lex = sanitize_lexeme(part)
        if lex and lex not in seen:
            seen.add(lex)
            out.append(lex)
    return out


def longest_surface_segments(
    query: str,
    store: GlossaryStore | None = None,
) -> list[tuple[str, frozenset[str] | None]]:
    """Split query into (segment, aliases|None) consuming longest surfaces first."""
    store = store or get_glossary_store()
    if not query or not store.surfaces_by_length:
        return [(query, None)] if query else []

    text = query
    n = len(text)
    claimed = [False] * n
    matches: list[tuple[int, int, frozenset[str]]] = []  # start, end, aliases

    lower_cache = {s: s.casefold() for s in store.surfaces_by_length}
    text_cf = text.casefold()

    for surface in store.surfaces_by_length:
        aliases = store.surfaces[surface]
        needle = lower_cache[surface]
        start = 0
        while True:
            idx = text_cf.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            if not any(claimed[i] for i in range(idx, end)):
                for i in range(idx, end):
                    claimed[i] = True
                matches.append((idx, end, aliases))
            start = idx + 1

    matches.sort(key=lambda m: m[0])
    segments: list[tuple[str, frozenset[str] | None]] = []
    cursor = 0
    for start, end, aliases in matches:
        if start > cursor:
            gap = text[cursor:start]
            if gap.strip():
                segments.append((gap, None))
        segments.append((text[start:end], aliases))
        cursor = end
    if cursor < n:
        tail = text[cursor:]
        if tail.strip():
            segments.append((tail, None))
    return segments or ([(query, None)] if query else [])


def build_expanded_tsquery(
    query: str,
    *,
    store: GlossaryStore | None = None,
    morph: KiwiMorphAnalyzer | None = None,
    segments: list[tuple[str, frozenset[str] | None]] | None = None,
) -> str:
    """Build ``to_tsquery('simple', ...)`` expression with OR synonym groups."""
    store = store or get_glossary_store()
    morph = morph or get_morph_analyzer()
    if segments is None:
        segments = longest_surface_segments(query, store)

    and_parts: list[str] = []
    for segment, aliases in segments:
        if aliases is None:
            lexemes = morph_lexemes(segment, morph)
            and_parts.extend(lexemes)
            continue
        # OR group: union of lexemes from every alias
        or_lexemes: list[str] = []
        seen: set[str] = set()
        for alias in sorted(aliases, key=len, reverse=True):
            for lex in morph_lexemes(alias, morph):
                if lex not in seen:
                    seen.add(lex)
                    or_lexemes.append(lex)
        if not or_lexemes:
            continue
        if len(or_lexemes) == 1:
            and_parts.append(or_lexemes[0])
        else:
            and_parts.append("(" + " | ".join(or_lexemes) + ")")

    if not and_parts:
        # fallback: plain morph of whole query as AND tokens
        return " & ".join(morph_lexemes(query, morph)) or sanitize_lexeme(query) or ""

    return " & ".join(and_parts)
