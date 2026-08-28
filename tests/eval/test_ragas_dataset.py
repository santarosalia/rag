from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.eval_ragas import (
    default_output_path,
    list_dataset_paths,
    load_dataset,
    resolve_defaults,
    validate_rows_for_metrics,
)


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
    assert defaults["runner"] == "api"
    assert defaults["metrics"]
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
