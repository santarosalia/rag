#!/usr/bin/env python3
"""Benchmark retrieval latency against the RAG API."""

import argparse
import statistics
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark RAG retrieval")
    parser.add_argument("query", help="Query text")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="dev-api-key-change-me")
    parser.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "sparse"])
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    headers = {"X-API-Key": args.api_key}
    client = httpx.Client(base_url=args.api_url, headers=headers, timeout=120.0)

    latencies: list[float] = []
    for i in range(args.iterations):
        payload = {"query": args.query, "mode": args.mode, "rerank": True}

        t0 = time.perf_counter()
        response = client.post("/v1/retrieve", json=payload)
        response.raise_for_status()
        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)
        result = response.json()
        backend_used = result.get("backend", "unknown")
        print(
            f"Run {i + 1}: {elapsed:.1f}ms, backend={backend_used}, "
            f"citations={len(result['citations'])}"
        )

    print(f"\nMode: {args.mode}")
    print(f"Mean: {statistics.mean(latencies):.1f}ms")
    print(f"P50:  {statistics.median(latencies):.1f}ms")
    if len(latencies) >= 2:
        print(f"P95:  {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.1f}ms")


if __name__ == "__main__":
    main()
