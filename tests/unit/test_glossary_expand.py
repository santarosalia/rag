"""Unit tests for glossary CSV parse + Sparse expand B."""

from __future__ import annotations

from pathlib import Path

from rag.db.models import GlossaryTerm
from rag.glossary.csv_io import parse_glossary_csv
from rag.glossary.expand import (
    build_expanded_tsquery,
    longest_surface_segments,
    morph_lexemes,
    sanitize_lexeme,
)
from rag.glossary.store import GlossaryStore
from rag.indexing.morphology import KiwiMorphAnalyzer


class _FakeMorph(KiwiMorphAnalyzer):
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._kiwi = object()  # skip lazy load
        self._mapping = mapping or {}

    def analyze(self, text: str) -> str:
        if text in self._mapping:
            return self._mapping[text]
        # naive: keep alnum/hangul runs
        import re

        parts = re.findall(r"[0-9A-Za-z가-힣]+", text)
        return " ".join(p for p in parts if len(p) > 1 or p.isalnum())


def test_sanitize_lexeme():
    assert sanitize_lexeme("코바코") == "코바코"
    assert sanitize_lexeme("KOBACO") == "KOBACO"
    assert sanitize_lexeme("a") == "a"
    assert sanitize_lexeme("은") == "은"
    assert sanitize_lexeme("hello-world") is None
    assert sanitize_lexeme("") is None


def test_parse_glossary_csv_bom_and_synonyms(tmp_path: Path):
    csv_path = tmp_path / "g.csv"
    csv_path.write_text(
        "\ufeffterm_id,standard_term,synonyms,category,definition,x,y,z,a,b,c,d\n"
        "AD-1,코바코,KOBACO|코바코|한국방송광고진흥공사,cat,def,,,,,,,,,,\n"
        "AD-2,결합판매,결합판매제도,,def2,,,,,,,,,,\n",
        encoding="utf-8",
    )
    rows = parse_glossary_csv(csv_path)
    assert len(rows) == 2
    assert rows[0]["id"] == "AD-1"
    assert rows[0]["standard_term"] == "코바코"
    # self-synonym dropped
    assert "코바코" not in rows[0]["synonyms"]
    assert "KOBACO" in rows[0]["synonyms"]
    assert rows[1]["synonyms"] == ["결합판매제도"]


def test_longest_surface_match_prefers_longer():
    store = GlossaryStore()
    store.load_rows(
        [
            GlossaryTerm(
                id="1",
                standard_term="결합판매",
                synonyms=["결합판매제도"],
                enabled=True,
            )
        ]
    )
    # rebuild surfaces so both map to same set
    segs = longest_surface_segments("결합판매제도 안내", store)
    matched = [s for s in segs if s[1] is not None]
    assert len(matched) == 1
    assert matched[0][0] == "결합판매제도"
    assert "결합판매" in matched[0][1]


def test_build_expanded_tsquery_or_group():
    store = GlossaryStore()
    store.load_rows(
        [
            GlossaryTerm(
                id="1",
                standard_term="코바코",
                synonyms=["KOBACO"],
                enabled=True,
            )
        ]
    )
    morph = _FakeMorph({"코바코": "코바코", "KOBACO": "KOBACO", "대행": "대행"})
    q = build_expanded_tsquery("코바코 대행", store=store, morph=morph)
    assert "|" in q
    assert "코바코" in q
    assert "KOBACO" in q
    assert "&" in q
    assert "대행" in q


def test_build_expanded_tsquery_no_match_falls_back():
    store = GlossaryStore()
    morph = _FakeMorph({"일반 질의": "일반 질의"})
    q = build_expanded_tsquery("일반 질의", store=store, morph=morph)
    assert q == "일반 & 질의"


def test_matched_glossary_definitions():
    store = GlossaryStore()
    store.load_rows(
        [
            GlossaryTerm(
                id="1",
                standard_term="코바코",
                synonyms=["KOBACO"],
                definition="방송광고 판매 대행 공공기관",
                enabled=True,
            )
        ]
    )
    from rag.glossary.expand import format_glossary_context, matched_glossary_definitions

    defs = matched_glossary_definitions("KOBACO 대행", store)
    assert defs == [("코바코", "방송광고 판매 대행 공공기관")]
    text = format_glossary_context(defs)
    assert "[Glossary]" in text
    assert "코바코" in text
