from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.eval_ragas import (
    aggregate_ragas_scores,
    annotate_raw_scores,
    attach_item_scores,
    citation_records,
    context_texts,
    default_output_path,
    is_dataset_enabled,
    list_dataset_paths,
    load_dataset,
    resolve_defaults,
    validate_rows_for_metrics,
)


def test_citation_records_from_api_payload():
    records = citation_records(
        [
            {
                "rank": 1,
                "filename": "manual.md",
                "page": 3,
                "score": 0.91,
                "chunk_id": "c1",
                "doc_id": "d1",
                "snippet": "  6월에 부과  ",
                "extra": "ignore",
            }
        ]
    )
    assert records == [
        {
            "rank": 1,
            "filename": "manual.md",
            "page": 3,
            "score": 0.91,
            "chunk_id": "c1",
            "doc_id": "d1",
            "snippet": "6월에 부과",
        }
    ]


def test_context_texts_prefers_content():
    records = citation_records(
        [
            {
                "rank": 1,
                "filename": "manual.md",
                "snippet": "preview",
                "content": "  full chunk  ",
            }
        ]
    )
    assert records[0]["content"] == "full chunk"
    assert context_texts(records) == ["full chunk"]


def test_resolve_defaults_citation_flags():
    defaults = resolve_defaults({})
    assert defaults["snippet"] is False
    assert defaults["content"] is True


def test_attach_item_scores_on_traces():
    traces = [{"id": "q1"}, {"id": "q2"}]
    attach_item_scores(
        traces,
        [{"faithfulness": 1.0}, {"faithfulness": float("nan")}],
    )
    assert traces[0]["scores"] == {"faithfulness": 1.0}
    assert traces[1]["scores"] == {"faithfulness": None}


def test_annotate_raw_scores_adds_item_id():
    traces = [{"id": "q1-optimized"}, {"id": "q1-user"}]
    raw = annotate_raw_scores(
        [{"faithfulness": 0.5, "context_recall": 1.0}, {"faithfulness": 1.0}],
        traces,
    )
    assert raw[0] == {
        "id": "q1-optimized",
        "faithfulness": 0.5,
        "context_recall": 1.0,
    }
    assert raw[1]["id"] == "q1-user"
    attach_item_scores(traces, raw)
    assert traces[0]["scores"] == {"faithfulness": 0.5, "context_recall": 1.0}


def test_aggregate_ragas_scores_from_list():
    result = SimpleNamespace(
        scores=[
            {"faithfulness": 1.0, "context_recall": 0.5},
            {"faithfulness": 0.5, "context_recall": float("nan")},
        ],
        _repr_dict={},
    )
    scores, raw = aggregate_ragas_scores(result)
    assert scores["faithfulness"] == 0.75
    assert scores["context_recall"] == 0.5
    assert raw is result.scores


def test_aggregate_ragas_scores_from_repr_dict():
    result = SimpleNamespace(
        scores=[{"faithfulness": 1.0}, {"faithfulness": 0.0}],
        _repr_dict={"faithfulness": 0.5},
    )
    scores, _ = aggregate_ragas_scores(result)
    assert scores == {"faithfulness": 0.5}


def test_is_dataset_enabled_defaults_true():
    assert is_dataset_enabled({}) is True
    assert is_dataset_enabled({"use": True}) is True
    assert is_dataset_enabled({"use": False}) is False
    assert is_dataset_enabled({"use": "false"}) is False


def test_resolve_defaults_runner_is_api():
    defaults = resolve_defaults({})
    assert defaults["runner"] == "api"
    assert defaults["api_url"] == "http://localhost:7500"


def test_default_output_path_under_results():
    when = datetime(2026, 8, 28, 9, 26, 0, tzinfo=UTC)
    path = default_output_path(Path("tests/eval/ragas_input/docuops_tax.yaml"), when)
    assert path == Path("results/ragas_docuops_tax_20260828T092600Z.json")
    dir_path = default_output_path(Path("tests/eval/ragas_input"), when)
    assert dir_path == Path("results/ragas_ragas_input_20260828T092600Z.json")

RAGAS_INPUT_DIR = Path("tests/eval/ragas_input")
RAGAS_TEMPLATE = Path("tests/eval/ragas_template.yaml")


def _ragas_input_yaml() -> list[Path]:
    return sorted(RAGAS_INPUT_DIR.glob("*.yaml")) + sorted(RAGAS_INPUT_DIR.glob("*.yml"))


def _rows_from_dataset(data: dict) -> list[dict]:
    return [
        {
            "user_input": item["question"],
            "retrieved_contexts": ["ctx"],
            "response": "ans",
            "reference": item.get("ground_truth") or item.get("reference") or "",
        }
        for item in data["items"]
    ]


def test_ragas_input_dir_has_yaml():
    assert RAGAS_INPUT_DIR.is_dir(), f"missing {RAGAS_INPUT_DIR}"
    files = _ragas_input_yaml()
    assert files, f"no YAML datasets in {RAGAS_INPUT_DIR}"
    assert list_dataset_paths(RAGAS_INPUT_DIR) == files


@pytest.mark.parametrize("path", _ragas_input_yaml(), ids=lambda p: p.name)
def test_ragas_input_loads(path: Path):
    data = load_dataset(path)
    defaults = resolve_defaults(data)
    assert "use" in data
    assert data["use"] in (True, False)
    assert len(data["items"]) >= 1
    for item in data["items"]:
        assert item.get("question"), f"{path.name} item {item.get('id')} missing question"


@pytest.mark.parametrize("path", _ragas_input_yaml(), ids=lambda p: p.name)
def test_ragas_input_reference_validation(path: Path):
    data = load_dataset(path)
    defaults = resolve_defaults(data)
    validate_rows_for_metrics(_rows_from_dataset(data), defaults["metrics"])


def test_ragas_template_loads():
    data = load_dataset(RAGAS_TEMPLATE)
    defaults = resolve_defaults(data)
    assert defaults["runner"] == "api"
    assert "faithfulness" in defaults["metrics"]
    assert len(data["items"]) >= 1


def test_ragas_template_reference_validation():
    data = load_dataset(RAGAS_TEMPLATE)
    defaults = resolve_defaults(data)
    validate_rows_for_metrics(_rows_from_dataset(data), defaults["metrics"])
