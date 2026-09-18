#!/usr/bin/env python3
"""Smoke tests for the optional CGAL spatial_sort adapter."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


POINTS = """\
0,0,0
1,0,0
0,1,0
0,0,1
1,1,1
-1,0,0
"""


def run_adapter(adapter: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(adapter), *args],
        check=False,
        text=True,
        capture_output=True,
    )


def read_order(path: Path) -> list[int]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [int(row["raw_index"]) for row in csv.DictReader(handle)]


def assert_adapter_policy(adapter: Path, root: Path, policy: str) -> None:
    points = root / "points.csv"
    points.write_text(POINTS, encoding="utf-8")
    order = root / f"{policy}.order.csv"
    metadata = root / f"{policy}.metadata.json"

    result = run_adapter(
        adapter,
        "--input",
        str(points),
        "--output",
        str(order),
        "--policy",
        policy,
        "--metadata-output",
        str(metadata),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)

    permutation = read_order(order)
    if sorted(permutation) != list(range(6)):
        raise AssertionError(f"{policy} did not emit a permutation: {permutation}")

    data = json.loads(metadata.read_text(encoding="utf-8"))
    expected = {
        "schema": "rch.cgal_adapter.metadata.v1",
        "spatial_sort_dimension": 3,
        "spatial_sort_policy": policy,
        "threshold_hilbert": 8,
        "threshold_multiscale": 64,
        "ratio": 0.125,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            raise AssertionError(f"{policy} metadata {key}: {data.get(key)!r} != {value!r}")
    for key in ("cgal_version", "cgal_version_nr", "cgal_git_hash"):
        if key not in data:
            raise AssertionError(f"{policy} metadata missing {key}")


def assert_adapter_accepts_empty_input(adapter: Path, root: Path) -> None:
    points = root / "empty.csv"
    points.write_text("", encoding="utf-8")
    order = root / "empty.order.csv"
    metadata = root / "empty.metadata.json"

    result = run_adapter(
        adapter,
        "--input",
        str(points),
        "--output",
        str(order),
        "--metadata-output",
        str(metadata),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    if read_order(order) != []:
        raise AssertionError("empty input did not emit an empty permutation")
    if json.loads(metadata.read_text(encoding="utf-8")).get("schema") != (
        "rch.cgal_adapter.metadata.v1"
    ):
        raise AssertionError("empty input did not emit adapter metadata")


def assert_adapter_skips_blank_rows_and_accepts_separators(adapter: Path, root: Path) -> None:
    points = root / "blank_and_semicolon.csv"
    points.write_text("\n  \t\n0,0,0\n\n1;0;0\n", encoding="utf-8")
    order = root / "blank_and_semicolon.order.csv"

    result = run_adapter(adapter, "--input", str(points), "--output", str(order))
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    permutation = read_order(order)
    if sorted(permutation) != [0, 1]:
        raise AssertionError(
            f"blank/semicolon input did not emit a 2-point permutation: {permutation}"
        )


def assert_adapter_rejects_malformed_rows(adapter: Path, root: Path) -> None:
    cases = {
        "short.csv": "0,0\n",
        "extra.csv": "0,0,0,0\n",
        "nonfinite.csv": "0,0,0\n1,nan,0\n",
    }
    for filename, text in cases.items():
        points = root / filename
        points.write_text(text, encoding="utf-8")
        result = run_adapter(
            adapter, "--input", str(points), "--output", str(root / f"{filename}.out")
        )
        if result.returncode == 0:
            raise AssertionError(f"malformed input unexpectedly succeeded: {filename}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: test_cgal_spatial_sort_adapter.py ADAPTER", file=sys.stderr)
        return 2

    adapter = Path(argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for policy in ("median", "middle"):
            assert_adapter_policy(adapter, root, policy)

        assert_adapter_accepts_empty_input(adapter, root)
        assert_adapter_skips_blank_rows_and_accepts_separators(adapter, root)
        assert_adapter_rejects_malformed_rows(adapter, root)

        result = run_adapter(
            adapter,
            "--input",
            str(root / "points.csv"),
            "--output",
            str(root / "bad_policy.csv"),
            "--policy",
            "unknown",
        )
        if result.returncode != 2:
            raise AssertionError("invalid policy did not return usage status 2")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
