#!/usr/bin/env python3
"""CLI for ingesting documents (source files via /documents, or Markdown via /parsed/file)."""

import argparse
import sys
from pathlib import Path

import httpx

_MD_SUFFIXES = {".md", ".markdown", ".txt"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into RAG")
    parser.add_argument("path", type=Path, help="File or directory to ingest")
    parser.add_argument("--api-url", default="http://localhost:8000", help="RAG API base URL")
    parser.add_argument("--group-id", required=True, help="Destination group id")
    parser.add_argument(
        "--markdown-only",
        action="store_true",
        help="Skip parser; POST /v1/documents/parsed/file for .md/.txt only",
    )
    args = parser.parse_args()

    path: Path = args.path
    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    files = [path] if path.is_file() else list(path.rglob("*"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    if args.markdown_only:
        files = [f for f in files if f.suffix.lower() in _MD_SUFFIXES]
    if not files:
        print("No files found", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client(base_url=args.api_url, timeout=600.0)
    endpoint = "/v1/documents/parsed/file" if args.markdown_only else "/v1/documents"

    for file_path in files:
        with file_path.open("rb") as f:
            response = client.post(
                endpoint,
                files={"file": (file_path.name, f)},
                data={"group_id": args.group_id},
            )
            response.raise_for_status()
            result = response.json()
            print(
                f"Uploaded {file_path.name} -> doc_id={result['doc_id']}, "
                f"job_id={result['job_id']}"
            )


if __name__ == "__main__":
    main()
