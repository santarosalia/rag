from pathlib import Path

from scripts.eval_ragas import load_dataset, resolve_defaults, validate_rows_for_metrics


def test_ragas_template_loads():
    path = Path("tests/eval/ragas_template.yaml")
    data = load_dataset(path)
    defaults = resolve_defaults(data)
    assert defaults["runner"] in ("direct", "api")
    assert "faithfulness" in defaults["metrics"]
    assert len(data["items"]) >= 1


def test_ragas_template_reference_validation():
    path = Path("tests/eval/ragas_template.yaml")
    data = load_dataset(path)
    defaults = resolve_defaults(data)
    rows = [
        {
            "user_input": item["question"],
            "retrieved_contexts": ["ctx"],
            "response": "ans",
            "reference": item.get("ground_truth", ""),
        }
        for item in data["items"]
    ]
    validate_rows_for_metrics(rows, defaults["metrics"])
