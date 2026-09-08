#!/usr/bin/env python3
"""CLI for ingesting documents (files via /documents/files, or ParseResponse JSON via /documents)."""

import argparse
import json
import sys
from pathlib import Path

import httpx

_PARSE_SUFFIXES = {".json"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into RAG")
    parser.add_argument("path", type=Path, help="File or directory to ingest")
    parser.add_argument("--api-url", default="http://localhost:8000", help="RAG API base URL")
    parser.add_argument("--group-id", required=True, help="Destination group id")
    parser.add_argument(
        "--parse-json",
        action="store_true",
        help="Skip parser; POST /v1/documents with ParseResponse or ResultItem[] JSON",
    )
    args = parser.parse_args()

    path: Path = args.path
    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    files = [path] if path.is_file() else list(path.rglob("*"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    if args.parse_json:
        files = [f for f in files if f.suffix.lower() in _PARSE_SUFFIXES]
    if not files:
        print("No files found", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client(base_url=args.api_url, timeout=600.0)

    for file_path in files:
        if args.parse_json:
            payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
            response = client.post(
                "/v1/documents",
                json={
                    "group_id": args.group_id,
                    "filename": file_path.name,
                    "parse": payload,
                },
            )
        else:
            with file_path.open("rb") as f:
                response = client.post(
                    "/v1/documents/files",
                    files={"file": (file_path.name, f)},
                    data={"group_id": args.group_id},
                )
        response.raise_for_status()
        result = response.json()
        print(
            f"Uploaded {file_path.name} -> doc_id={result['doc_id']}, "
            f"status={result['status']}, chunks={result.get('chunk_count')}"
        )


if __name__ == "__main__":
    main()
