#!/usr/bin/env python3
"""Run isolated, balanced CGAL k-d-tree comparisons using the shared application C0 inputs."""
from __future__ import annotations
import argparse
import csv
import json
import platform
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis/scripts"))
from analyze_tree_benchmarks import BACKENDS, analyze, digest
sys.path.insert(0, str(ROOT))
from experiments.application_layouts import APPLICATION_OUTPUT_ROOT, is_application_source


def frozen_file(path: str, checksum: str) -> Path:
    target = (ROOT / path).resolve()
    target.relative_to(ROOT)
    if digest(target) != checksum:
        raise ValueError(f"source checksum mismatch: {path}")
    return target


def run(args: argparse.Namespace) -> None:
    source = args.source_root.resolve() / "run_manifest.json"
    data = json.loads(source.read_text())
    if not is_application_source(data):
        raise ValueError("expected shared application input manifest; run make app-query first")
    ids = args.dataset or data["expected_dataset_ids"]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", id_) for id_ in ids):
        raise ValueError("duplicate/invalid dataset selection")
    records = {d["dataset_id"]: d for d in data["datasets"]}
    if not ids or set(ids) - records.keys():
        raise ValueError("unknown/empty dataset selection")
    if args.output_dir.exists():
        raise ValueError("output root already exists; choose a new TREE_OUTPUT_DIR")
    # Validate inputs before creating the output root; never regenerate existing measurements.
    inputs = {}
    for id_ in ids:
        d = records[id_]
        points = frozen_file(d["input_csv"], d["input_csv_sha256"])
        workload = d["query_workload"]
        queries = frozen_file(workload["file"], workload["file_sha256"])
        query_ids = [r["query_id"] for r in csv.DictReader(queries.open())]
        if len(query_ids) != data["query_count_per_dataset_layout"] or len(set(query_ids)) != len(query_ids):
            raise ValueError("incomplete or duplicate source queries")
        orders = {}
        for key in ("A3_isotropic_hilbert", "A6_rch"):
            order = d["order_files"][key]
            orders[key] = frozen_file(order["path"], order["sha256"])
        inputs[id_] = points, queries, orders, query_ids
    binary = args.binary.resolve()
    binary_hash = digest(binary)
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "source_manifest.json").write_text(source.read_text())
    state = {"schema": "rch.tree_benchmark.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
             "platform": platform.platform(), "binary_sha256": binary_hash,
             "source_manifest_sha256": digest(source), "process_blocks": args.repeats,
             "bucket_size": args.bucket, "seed": args.seed, "backends": list(BACKENDS),
             "datasets": [], "schedule": [], "files_sha256": {},
             "source_rch_layout": "A6_rch (C0 uniform)",
             "scope": "Static exact 3D windows; warm page-file group and resident-memory group are analyzed separately.",
             "preparation_scope": "Backend preparation excludes input loading and prior SFC ordering. Source SFC ordering costs are retained separately; no end-to-end break-even claim.",
             "rss_scope": "Fresh process per dataset/backend/block; cumulative peak includes original data, backend, warmup and correctness oracle.",
             "tree_configuration": {"library": "CGAL", "splitter": "Sliding_midpoint", "extended_nodes": False, "points_cache": False, "parallel": False, "epsilon": 0},
             "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in [Path(__file__).resolve(), ROOT / "adapters/cgal/cgal_tree_benchmark.cpp", ROOT / "analysis/scripts/analyze_tree_benchmarks.py", ROOT / "experiments/application_layouts.py"]}}
    cache = binary.parents[2] / "CMakeCache.txt"
    state["build_configuration"] = None
    if cache.is_file():
        state["build_configuration"] = {line.split(":", 1)[0]: line.split("=", 1)[1]
            for line in cache.read_text().splitlines()
            if line.startswith(("CMAKE_CXX_COMPILER:", "CMAKE_BUILD_TYPE:", "CMAKE_CXX_FLAGS:", "CMAKE_CXX_FLAGS_RELEASE:", "CGAL_DIR:")) and "=" in line}
    rng = random.Random(args.seed)
    for id_ in ids:
        points, queries, orders, query_ids = inputs[id_]
        d = records[id_]
        state["datasets"].append({"dataset_id": id_, "point_count": d["point_count"], "query_ids": query_ids,
                                  "input_sha256": digest(points), "query_sha256": digest(queries),
                                  "source_ordering_wall_seconds": d["ordering_wall_seconds"]})
        for block in range(args.repeats):
            schedule = list(BACKENDS)
            rng.shuffle(schedule)
            state["schedule"].append({"dataset_id": id_, "block": block, "order": schedule})
            for backend in schedule:
                output = args.output_dir / id_ / f"block_{block}" / backend
                output.parent.mkdir(parents=True, exist_ok=True)
                command = [str(binary), "--points", str(points), "--queries", str(queries), "--backend", backend,
                           "--output", str(output.resolve()), "--repeats", "1", "--bucket", str(args.bucket),
                           "--seed", str(args.seed + block)]
                if backend.startswith("hilbert"):
                    command += ["--order", str(orders["A3_isotropic_hilbert"])]
                elif backend.startswith("rch"):
                    command += ["--order", str(orders["A6_rch"])]
                print(f"[tree] {id_} block={block + 1}/{args.repeats} {backend}", flush=True)
                completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
                (output.parent / f"{backend}.log").write_text(completed.stdout + completed.stderr)
                if completed.returncode:
                    raise RuntimeError(f"backend failed; see {output.parent / (backend + '.log')}")
    if digest(binary) != binary_hash or digest(source) != state["source_manifest_sha256"]:
        raise ValueError("binary/source manifest changed during the benchmark")
    for path in sorted(args.output_dir.rglob("*")):
        if path.is_file():
            state["files_sha256"][str(path.relative_to(args.output_dir))] = digest(path)
    (args.output_dir / "run_manifest.json").write_text(json.dumps(state, indent=2) + "\n")
    analyze(args.output_dir, args.output_dir / "analysis")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT / APPLICATION_OUTPUT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/outputs/tree_benchmark/full_benchmark")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--repeats", type=int, default=5, help="fresh process blocks; one warmup + one measured workload per process")
    parser.add_argument("--bucket", type=int, default=128)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10000 or not 1 <= args.bucket <= 10000 or args.seed < 0:
        parser.error("repeats/bucket must be 1..10000 and seed nonnegative")
    run(args)


if __name__ == "__main__":
    main()
