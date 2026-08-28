#!/usr/bin/env python3
"""Run RAGAS evaluation from a YAML dataset against the RAG stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from openai import OpenAI

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "faithfulness": {
        "needs_reference": False,
        "needs_embeddings": False,
    },
    "answer_relevancy": {
        "needs_reference": False,
        "needs_embeddings": True,
    },
    "context_recall": {
        "needs_reference": True,
        "needs_embeddings": False,
    },
    "context_precision": {
        "needs_reference": True,
        "needs_embeddings": False,
    },
}


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not data.get("items"):
        raise ValueError(f"No items in {path}")
    return data


def list_dataset_paths(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted({*path.glob("*.yaml"), *path.glob("*.yml")})
        if not files:
            raise ValueError(f"No YAML datasets in {path}")
        return files
    return [path]


def load_dotenv_file(path: Path = Path(".env")) -> None:
    """Fill os.environ from .env without overwriting existing variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def llm_env() -> tuple[str, str]:
    load_dotenv_file()
    base_url = os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1"
    api_key = os.environ.get("LLM_API_KEY") or ""
    return base_url, api_key


RESULTS_DIR = Path("results")


def default_output_path(dataset: Path, when: datetime | None = None) -> Path:
    stamp = (when or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    label = dataset.stem if dataset.suffix else dataset.name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "run"
    return RESULTS_DIR / f"ragas_{safe}_{stamp}.json"


def resolve_defaults(data: dict[str, Any]) -> dict[str, Any]:
    defaults = data.get("defaults") or {}
    return {
        "runner": defaults.get("runner", "api"),
        "api_url": defaults.get("api_url", "http://localhost:7500"),
        "group_id": defaults.get("group_id"),
        "top_k": defaults.get("top_k", 5),
        "include_citations": defaults.get("include_citations", True),
        "snippet": defaults.get("snippet", False),
        "content": defaults.get("content", True),
        "metrics": defaults.get(
            "metrics", ["faithfulness", "context_recall", "context_precision"]
        ),
        "thresholds": defaults.get("thresholds") or {},
        "judge": defaults.get("judge") or {},
        "embeddings": defaults.get("embeddings") or {},
    }


def build_openai_client(cfg: dict[str, Any], fallback_base_url: str, fallback_key: str) -> OpenAI:
    api_key_env = cfg.get("api_key_env", "LLM_API_KEY")
    api_key = os.environ.get(api_key_env) or fallback_key or "EMPTY"
    base_url = cfg.get("base_url") or fallback_base_url
    return OpenAI(api_key=api_key, base_url=base_url.rstrip("/"))


def build_metrics(
    metric_names: list[str],
    llm: Any,
    embeddings: Any | None,
) -> tuple[list[Any], list[str]]:
    # ragas 0.4 `evaluate()` still requires legacy Metric objects.
    # ragas.metrics.collections.* is the newer API and is not a Metric subclass.
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.metrics._context_recall import ContextRecall
    from ragas.metrics._faithfulness import Faithfulness

    classes = {
        "faithfulness": Faithfulness,
        "answer_relevancy": AnswerRelevancy,
        "context_recall": ContextRecall,
        "context_precision": ContextPrecision,
    }

    metrics: list[Any] = []
    resolved: list[str] = []
    for name in metric_names:
        spec = METRIC_SPECS.get(name)
        if spec is None:
            raise ValueError(f"Unknown metric: {name}. Choose from: {', '.join(METRIC_SPECS)}")
        cls = classes[name]
        if spec["needs_embeddings"]:
            if embeddings is None:
                raise ValueError(
                    f"Metric '{name}' requires embeddings config in YAML defaults.embeddings"
                )
            metrics.append(cls(llm=llm, embeddings=embeddings))
        else:
            metrics.append(cls(llm=llm))
        resolved.append(name)
    return metrics, resolved


def citation_records(raw: Any) -> list[dict[str, Any]]:
    """Keep rank/filename/page/score and whatever body fields the API returned."""
    records: list[dict[str, Any]] = []
    for item in raw or []:
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            continue
        record: dict[str, Any] = {
            "rank": data.get("rank"),
            "filename": data.get("filename") or "",
            "page": data.get("page"),
            "score": data.get("score"),
            "chunk_id": data.get("chunk_id"),
            "doc_id": data.get("doc_id"),
        }
        if data.get("snippet") is not None:
            record["snippet"] = str(data.get("snippet") or "").strip()
        if data.get("content") is not None:
            record["content"] = str(data.get("content") or "").strip()
        records.append(record)
    return records


def context_texts(citations: list[dict[str, Any]]) -> list[str]:
    """RAGAS retrieved_contexts: full chunk content, snippet only as fallback."""
    texts: list[str] = []
    for citation in citations:
        body = str(citation.get("content") or citation.get("snippet") or "").strip()
        if body:
            texts.append(body)
    return texts


def annotate_raw_scores(raw_scores: Any, traces: list[dict[str, Any]]) -> Any:
    """Prefix each per-item score dict with the YAML item id."""
    if not isinstance(raw_scores, list):
        return raw_scores
    annotated: list[Any] = []
    for i, row in enumerate(raw_scores):
        if not isinstance(row, dict):
            annotated.append(row)
            continue
        item_id = traces[i].get("id") if i < len(traces) else None
        metrics = {k: v for k, v in row.items() if k != "id"}
        if item_id is None:
            annotated.append(metrics)
        else:
            annotated.append({"id": item_id, **metrics})
    return annotated


def attach_item_scores(traces: list[dict[str, Any]], raw_scores: Any) -> None:
    if not isinstance(raw_scores, list):
        return
    for trace, row in zip(traces, raw_scores):
        if isinstance(row, dict):
            metrics = {k: v for k, v in row.items() if k != "id"}
            trace["scores"] = json_safe(metrics)


async def query_direct(
    question: str,
    group_id: str | None,
    top_k: int,
) -> tuple[str, list[str], dict[str, float], str, list[dict[str, Any]]]:
    try:
        from rag.generation.service import QueryService
    except ModuleNotFoundError as e:
        raise SystemExit(
            "direct runner imports QueryService in-process and needs the `rag` package "
            "(pip install -e .). "
            "With Docker API on the host, use:\n"
            "  python scripts/eval_ragas.py tests/eval/ragas_input "
            "--runner api --api-url http://localhost:7500 --dry-run"
        ) from e

    service = QueryService()
    try:
        response = await service.query(query=question, group_id=group_id, top_k=top_k)
        citations = citation_records(response.citations)
        return (
            response.answer,
            context_texts(citations),
            response.latency_ms,
            response.backend,
            citations,
        )
    finally:
        await service.retrieval.close()


def query_api(
    client: httpx.Client,
    question: str,
    group_id: str | None,
    top_k: int,
    include_citations: bool,
    snippet: bool,
    content: bool,
) -> tuple[str, list[str], dict[str, float], str, list[dict[str, Any]]]:
    payload: dict[str, Any] = {
        "query": question,
        "top_k": top_k,
        "include_citations": include_citations,
        "snippet": snippet,
        "content": content,
    }
    if group_id:
        payload["group_id"] = group_id

    response = client.post("/v1/query", json=payload)
    response.raise_for_status()
    data = response.json()
    citations = citation_records(data.get("citations") or [])
    return (
        data.get("answer", ""),
        context_texts(citations),
        data.get("latency_ms") or {},
        data.get("backend", "unknown"),
        citations,
    )


async def collect_samples(
    data: dict[str, Any],
    defaults: dict[str, Any],
    runner: str,
    api_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    client: httpx.Client | None = None
    if runner == "api":
        client = httpx.Client(base_url=api_url, timeout=120.0)

    try:
        for item in data["items"]:
            if item.get("skip"):
                continue

            question = item["question"]
            group_id = item.get("group_id", defaults["group_id"])
            top_k = item.get("top_k", defaults["top_k"])
            reference = (item.get("ground_truth") or item.get("reference") or "").strip()

            if runner == "direct":
                answer, contexts, latency_ms, backend, citations = await query_direct(
                    question, group_id, top_k
                )
            else:
                assert client is not None
                answer, contexts, latency_ms, backend, citations = query_api(
                    client,
                    question,
                    group_id,
                    top_k,
                    defaults["include_citations"],
                    defaults["snippet"],
                    defaults["content"],
                )

            if not contexts:
                print(f"warning: {item.get('id', '?')} returned no contexts", file=sys.stderr)

            row: dict[str, Any] = {
                "user_input": question,
                "retrieved_contexts": contexts,
                "response": answer,
            }
            if reference:
                row["reference"] = reference

            rows.append(row)
            traces.append(
                {
                    "id": item.get("id"),
                    "question": question,
                    "group_id": group_id,
                    "backend": backend,
                    "context_count": len(citations) or len(contexts),
                    "latency_ms": latency_ms,
                    "answer": answer,
                    "citations": citations,
                }
            )
    finally:
        if client is not None:
            client.close()

    return rows, traces


def validate_rows_for_metrics(rows: list[dict[str, Any]], metric_names: list[str]) -> None:
    needs_reference = any(METRIC_SPECS[n]["needs_reference"] for n in metric_names)
    if needs_reference:
        missing = [i for i, row in enumerate(rows) if not row.get("reference")]
        if missing:
            raise ValueError(
                "Some metrics require ground_truth/reference on every item. "
                f"Missing on row indexes: {missing}"
            )


def aggregate_ragas_scores(result: Any) -> tuple[dict[str, float], Any]:
    """RAGAS 0.4 `EvaluationResult.scores` is a list of per-sample dicts, not a mapping."""
    raw = getattr(result, "scores", None)
    means = getattr(result, "_repr_dict", None)
    if isinstance(means, dict) and means:
        scores: dict[str, float] = {}
        for key, value in means.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number:  # drop NaN
                scores[key] = number
        if scores:
            return scores, raw

    if isinstance(raw, dict):
        scores = {}
        for key, value in raw.items():
            try:
                scores[key] = float(value)
            except (TypeError, ValueError):
                continue
        return scores, raw

    if isinstance(raw, list) and raw:
        scores = {}
        for key in raw[0]:
            values: list[float] = []
            for row in raw:
                try:
                    number = float(row[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if number == number:
                    values.append(number)
            if values:
                scores[key] = sum(values) / len(values)
        return scores, raw

    return {}, raw


def json_safe(value: Any) -> Any:
    """Replace NaN/Inf so reports stay valid JSON."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def run_ragas(
    rows: list[dict[str, Any]],
    metric_names: list[str],
    judge_cfg: dict[str, Any],
    embeddings_cfg: dict[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    base_url, api_key = llm_env()
    judge_client = build_openai_client(
        judge_cfg,
        fallback_base_url=base_url,
        fallback_key=api_key,
    )
    judge_model = (
        judge_cfg.get("model")
        or os.environ.get("LLM_MODEL")
        or "gpt-4o-mini"
    )
    llm = llm_factory(
        judge_model,
        client=judge_client,
        temperature=judge_cfg.get("temperature", 0.0),
        max_tokens=judge_cfg.get("max_tokens", 4096),
    )

    embeddings = None
    if any(METRIC_SPECS[n]["needs_embeddings"] for n in metric_names):
        emb_client = build_openai_client(
            embeddings_cfg or judge_cfg,
            fallback_base_url=base_url,
            fallback_key=api_key,
        )
        emb_model = (embeddings_cfg or {}).get("model", "text-embedding-3-small")
        embeddings = embedding_factory("openai", model=emb_model, client=emb_client)

    metrics, resolved_names = build_metrics(metric_names, llm, embeddings)
    dataset = EvaluationDataset.from_list(rows)
    result = evaluate(dataset=dataset, metrics=metrics, llm=llm, show_progress=True)

    scores, raw_scores = aggregate_ragas_scores(result)
    details = {
        "scores": scores,
        "raw": json_safe(raw_scores),
        "metric_names": resolved_names,
    }
    return scores, details


def check_thresholds(scores: dict[str, float], thresholds: dict[str, float]) -> dict[str, bool]:
    return {
        name: scores.get(name, 0.0) >= threshold
        for name, threshold in thresholds.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation from YAML")
    parser.add_argument(
        "dataset",
        type=Path,
        help="Path to a ragas YAML dataset or a directory of YAML files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON report path (default: results/ragas_<dataset>_<timestamp>.json)",
    )
    parser.add_argument(
        "--runner",
        choices=["direct", "api"],
        help="Override defaults.runner (default: api)",
    )
    parser.add_argument("--api-url", help="Override defaults.api_url")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect RAG answers only; skip RAGAS judge",
    )
    args = parser.parse_args()
    load_dotenv_file()

    paths = list_dataset_paths(args.dataset)
    reports: list[dict[str, Any]] = []
    any_fail = False

    for dataset_path in paths:
        data = load_dataset(dataset_path)
        defaults = resolve_defaults(data)
        runner = args.runner or defaults["runner"]
        api_url = args.api_url or defaults["api_url"]
        metric_names = list(defaults["metrics"])

        print(f"Dataset: {data.get('name', dataset_path.name)} ({dataset_path})")
        print(f"Runner: {runner}")
        print(f"Metrics: {', '.join(metric_names)}")

        rows, traces = asyncio.run(collect_samples(data, defaults, runner, api_url))
        validate_rows_for_metrics(rows, metric_names)

        report: dict[str, Any] = {
            "name": data.get("name"),
            "description": data.get("description"),
            "dataset_path": str(dataset_path),
            "run_at": datetime.now(UTC).isoformat(),
            "runner": runner,
            "metrics": metric_names,
            "item_count": len(rows),
            "traces": traces,
        }

        if args.dry_run:
            report["dry_run"] = True
        else:
            scores, ragas_details = run_ragas(
                rows,
                metric_names,
                defaults["judge"],
                defaults["embeddings"],
            )
            thresholds = defaults["thresholds"]
            passed = check_thresholds(scores, thresholds) if thresholds else {}

            report["scores"] = scores
            report["thresholds"] = thresholds
            report["passed"] = passed
            report["all_thresholds_met"] = all(passed.values()) if passed else None
            ragas_details["raw"] = annotate_raw_scores(
                ragas_details.get("raw"), traces
            )
            report["ragas"] = ragas_details
            attach_item_scores(traces, ragas_details.get("raw"))

            print("\n--- RAGAS scores ---")
            for name, value in scores.items():
                mark = ""
                if name in passed:
                    mark = " PASS" if passed[name] else " FAIL"
                print(f"{name}: {value:.4f}{mark}")

            if passed and not all(passed.values()):
                any_fail = True

        reports.append(report)

    output = args.output or default_output_path(args.dataset)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload: Any = reports[0] if len(reports) == 1 else {"datasets": reports}
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"\nWrote {output}")

    if any_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
