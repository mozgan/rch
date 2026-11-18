#!/usr/bin/env python3
"""Verify that a consumer snapshot belongs to the configured shared application run."""
from __future__ import annotations
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve(benchmark: Path, fallback: Path, repository: Path = ROOT) -> Path:
    snapshot = benchmark / "source_manifest.json"
    if snapshot.is_file():
        current = repository / fallback / "run_manifest.json"
        if not current.is_file() or current.read_bytes() != snapshot.read_bytes():
            raise ValueError("benchmark belongs to a different application run; rerun against APPLICATION_QUERY_OUTPUT_DIR")
    return fallback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True, help="configured shared application source")
    args = parser.parse_args()
    print(resolve(args.benchmark_root, args.fallback))


if __name__ == "__main__":
    main()
