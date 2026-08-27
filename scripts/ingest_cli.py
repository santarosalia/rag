#!/usr/bin/env python3
"""CLI for ingesting documents from the filesystem."""

import argparse
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into RAG")
    parser.add_argument("path", type=Path, help="File or directory to ingest")
    parser.add_argument("--api-url", default="http://localhost:8000", help="RAG API base URL")
    parser.add_argument("--api-key", default="dev-api-key-change-me", help="API key")
    parser.add_argument("--group-id", required=True, help="Destination group UUID")
    args = parser.parse_args()

    path: Path = args.path
    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    files = [path] if path.is_file() else list(path.rglob("*"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]

    headers = {"X-API-Key": args.api_key}
    client = httpx.Client(base_url=args.api_url, headers=headers, timeout=120.0)

    for file_path in files:
        with file_path.open("rb") as f:
            data = {"group_id": args.group_id}
            response = client.post(
                "/v1/documents",
                files={"file": (file_path.name, f)},
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
