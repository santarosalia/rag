#!/usr/bin/env python3
"""Run RAGAS evaluation from a YAML dataset against the RAG stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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


def resolve_defaults(data: dict[str, Any]) -> dict[str, Any]:
    defaults = data.get("defaults") or {}
    return {
        "runner": defaults.get("runner", "direct"),
        "api_url": defaults.get("api_url", "http://localhost:8000"),
        "group_id": defaults.get("group_id"),
        "top_k": defaults.get("top_k", 5),
        "include_citations": defaults.get("include_citations", True),
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
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    classes = {
        "faithfulness": Faithfulness,
        "answer_relevancy": AnswerRelevancy,
        "context_recall": ContextRecall,
        "context_precision": ContextPrecisionWithReference,
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


async def query_direct(
    question: str,
    group_id: str | None,
    top_k: int,
) -> tuple[str, list[str], dict[str, float], str]:
    from rag.generation.service import QueryService

    service = QueryService()
    try:
        response = await service.query(query=question, group_id=group_id, top_k=top_k)
        contexts = [
            (c.content or c.snippet).strip()
            for c in response.citations
            if (c.content or c.snippet).strip()
        ]
        return response.answer, contexts, response.latency_ms, response.backend
    finally:
        await service.retrieval.close()


def query_api(
    client: httpx.Client,
    question: str,
    group_id: str | None,
    top_k: int,
    include_citations: bool,
) -> tuple[str, list[str], dict[str, float], str]:
    payload: dict[str, Any] = {
        "query": question,
        "top_k": top_k,
        "include_citations": include_citations,
    }
    if group_id:
        payload["group_id"] = group_id

    response = client.post("/v1/query", json=payload)
    response.raise_for_status()
    data = response.json()
    contexts = [
        str(c.get("snippet", "")).strip()
        for c in data.get("citations", [])
        if str(c.get("snippet", "")).strip()
    ]
    return (
        data.get("answer", ""),
        contexts,
        data.get("latency_ms") or {},
        data.get("backend", "unknown"),
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
                answer, contexts, latency_ms, backend = await query_direct(
                    question, group_id, top_k
                )
            else:
                assert client is not None
                answer, contexts, latency_ms, backend = query_api(
                    client,
                    question,
                    group_id,
                    top_k,
                    defaults["include_citations"],
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
                    "context_count": len(contexts),
                    "latency_ms": latency_ms,
                    "answer_preview": answer[:200],
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


def run_ragas(
    rows: list[dict[str, Any]],
    metric_names: list[str],
    judge_cfg: dict[str, Any],
    embeddings_cfg: dict[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    from rag.config import get_settings

    settings = get_settings()
    judge_client = build_openai_client(
        judge_cfg,
        fallback_base_url=settings.llm_base_url,
        fallback_key=settings.llm_api_key,
    )
    judge_model = judge_cfg.get("model") or settings.yaml_config.get("llm", {}).get(
        "model", "gpt-4o-mini"
    )
    llm = llm_factory(judge_model, client=judge_client)

    embeddings = None
    if any(METRIC_SPECS[n]["needs_embeddings"] for n in metric_names):
        emb_client = build_openai_client(
            embeddings_cfg or judge_cfg,
            fallback_base_url=settings.llm_base_url,
            fallback_key=settings.llm_api_key,
        )
        emb_model = (embeddings_cfg or {}).get("model", "text-embedding-3-small")
        embeddings = embedding_factory("openai", model=emb_model, client=emb_client)

    metrics, resolved_names = build_metrics(metric_names, llm, embeddings)
    dataset = EvaluationDataset.from_list(rows)
    result = evaluate(dataset=dataset, metrics=metrics, llm=llm, show_progress=True)

    scores: dict[str, float] = {}
    for name in resolved_names:
        if name in result.scores:
            scores[name] = float(result.scores[name])

    details = {
        "scores": scores,
        "raw": {k: float(v) for k, v in result.scores.items()},
    }
    return scores, details


def check_thresholds(scores: dict[str, float], thresholds: dict[str, float]) -> dict[str, bool]:
    return {
        name: scores.get(name, 0.0) >= threshold
        for name, threshold in thresholds.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation from YAML")
    parser.add_argument("dataset", type=Path, help="Path to ragas YAML dataset")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    parser.add_argument("--runner", choices=["direct", "api"], help="Override defaults.runner")
    parser.add_argument("--api-url", help="Override defaults.api_url")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect RAG answers only; skip RAGAS judge",
    )
    args = parser.parse_args()

    data = load_dataset(args.dataset)
    defaults = resolve_defaults(data)
    runner = args.runner or defaults["runner"]
    api_url = args.api_url or defaults["api_url"]
    metric_names = list(defaults["metrics"])

    print(f"Dataset: {data.get('name', args.dataset.name)}")
    print(f"Runner: {runner}")
    print(f"Metrics: {', '.join(metric_names)}")

    rows, traces = asyncio.run(collect_samples(data, defaults, runner, api_url))
    validate_rows_for_metrics(rows, metric_names)

    report: dict[str, Any] = {
        "name": data.get("name"),
        "description": data.get("description"),
        "dataset_path": str(args.dataset),
        "run_at": datetime.now(UTC).isoformat(),
        "runner": runner,
        "metrics": metric_names,
        "item_count": len(rows),
        "traces": traces,
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, ensure_ascii=False, indent=2))
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
        report["ragas"] = ragas_details

        print("\n--- RAGAS scores ---")
        for name, value in scores.items():
            mark = ""
            if name in passed:
                mark = " PASS" if passed[name] else " FAIL"
            print(f"{name}: {value:.4f}{mark}")

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nWrote {args.output}")

        if passed and not all(passed.values()):
            sys.exit(1)


if __name__ == "__main__":
    main()
