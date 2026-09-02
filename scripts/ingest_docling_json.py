#!/usr/bin/env python3
"""CLI for ingesting Docling layout JSON into RAG."""

import argparse
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Docling layout JSON (one item = one chunk) into RAG"
    )
    parser.add_argument("path", type=Path, help="Docling JSON file or directory")
    parser.add_argument("--api-url", default="http://localhost:8000", help="RAG API base URL")
    parser.add_argument("--group-id", required=True, help="Destination group id")
    args = parser.parse_args()

    path: Path = args.path
    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    files = [path] if path.is_file() else sorted(path.rglob("*.json"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    if not files:
        print(f"No JSON files found under {path}", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client(base_url=args.api_url, timeout=120.0)

    for file_path in files:
        with file_path.open("rb") as f:
            data = {"group_id": args.group_id}
            response = client.post(
                "/v1/documents/docling/file",
                files={"file": (file_path.name, f, "application/json")},
                data=data,
            )
            response.raise_for_status()
            result = response.json()
            print(
                f"Uploaded {file_path.name} -> doc_id={result['doc_id']}, "
                f"job_id={result['job_id']}"
            )


if __name__ == "__main__":
    main()
