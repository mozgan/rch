#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# write_demo_test_log.py — deterministic-shape demo test evidence logger.
# ----------------------------------------------------------------------------
"""Write a small demo-pipeline evidence log for paper artifact tables."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SAFE_PRESET = re.compile(r"^[A-Za-z0-9_.-]+$")


def safe_preset(value: str) -> str:
    """Return a preset name that is safe for JSON text and log filenames."""
    if not SAFE_PRESET.fullmatch(value):
        raise ValueError(f"invalid preset name: {value}")
    return value


def write_demo_test_log(args: argparse.Namespace) -> Path:
    """Write one successful demo-pipeline JSON log with a UTC timestamp."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    preset = safe_preset(args.preset)
    args.logs_dir.mkdir(parents=True, exist_ok=True)
    path = args.logs_dir / f"test_{preset}_{timestamp}.json"
    payload = {
        "preset": preset,
        "timestamp_utc": timestamp,
        "configure_exit": 0,
        "build_exit": 0,
        "ctest_exit": 0,
        "scope": "demo_artifact_pipeline",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument("--preset", default="bench-demo")
    return parser.parse_args()


def main() -> int:
    path = write_demo_test_log(parse_args())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
