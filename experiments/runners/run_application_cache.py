#!/usr/bin/env python3
"""Separate, resumable Linux page-cache experiment on the shared frozen application files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = [
    "experiments/runners/run_application_cache.py",
    "src/cli/rch_application_cache_probe.cpp",
    "include/rch/application/page_file.hpp",
    "include/rch/application/page_directory.hpp",
    "include/rch/application/window_query.hpp",
    "include/rch/core/sha256.hpp",
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def checked(path: str, expected: str) -> Path:
    result = ROOT / path
    if sha(result) != expected:
        raise ValueError(f"source checksum mismatch: {result}")
    return result.resolve()


def prepare(args) -> tuple[dict, list[dict]]:
    source_path = args.application_root / "run_manifest.json"
    source = json.loads(source_path.read_text())
    for path, checksum in source["source_sha256"].items():
        checked(path, checksum)
    datasets = source["datasets"]
    if args.dataset:
        unknown = set(args.dataset) - {d["dataset_id"] for d in datasets}
        if unknown:
            raise ValueError(f"unknown datasets: {sorted(unknown)}")
        datasets = [d for d in datasets if d["dataset_id"] in args.dataset]
    tasks = []
    for dataset in datasets:
        identifier = dataset["dataset_id"]
        q = dataset["query_results"]["query_windows.csv"]
        oracle = dataset["query_results"]["query_results.csv"]
        query_path = checked(q["path"], q["sha256"])
        oracle_path = checked(oracle["path"], oracle["sha256"])
        queries = read_csv(query_path)
        oracle_rows = read_csv(oracle_path)
        if len(queries) != source["query_count_per_dataset_layout"]:
            raise ValueError("query count differs from frozen application protocol")
        for layout in dataset["layout_schedule"]:
            storage = dataset["storage_integrity"][layout]
            page = checked(storage["page_file"], storage["page_file_sha256"])
            index = checked(storage["index_file"], storage["index_file_sha256"])
            selected = [r for r in oracle_rows if r["layout_id"] == layout]
            by_id = {r["query_id"]: r for r in selected}
            if len(by_id) != len(queries) or len(selected) != len(queries):
                raise ValueError("missing or duplicate frozen oracle rows")
            lines = []
            for query in queries:
                expected = by_id[query["query_id"]]
                if expected["oracle_match"] != "true":
                    raise ValueError("frozen full-scan oracle failed")
                fields = [
                    query[k]
                    for k in (
                        "query_id",
                        "min_x",
                        "min_y",
                        "min_z",
                        "max_x",
                        "max_y",
                        "max_z",
                    )
                ]
                fields += [expected["result_count"], expected["result_ids_sha256"]]
                if any(any(c.isspace() for c in f) for f in fields):
                    raise ValueError("whitespace in query/oracle field")
                lines.append("\t".join(fields))
            tasks.append(
                {
                    "dataset_id": identifier,
                    "layout_id": layout,
                    "page": str(page),
                    "index": str(index),
                    "page_sha256": storage["page_file_sha256"],
                    "index_sha256": storage["index_file_sha256"],
                    "query_sha256": q["sha256"],
                    "oracle_sha256": oracle["sha256"],
                    "query_ids": [r["query_id"] for r in queries],
                    "oracle_tsv": "\n".join(lines) + "\n",
                }
            )
    if not tasks:
        raise ValueError(
            "application manifest contains no selected dataset/layout tasks"
        )
    identity = {
        "application_manifest_sha256": sha(source_path),
        "application_root": str(args.application_root),
        "repeats": args.repeats,
        "seed": args.seed,
        "datasets": [d["dataset_id"] for d in datasets],
        "binary": str(args.probe_bin),
        "binary_sha256": sha(args.probe_bin),
        "source_sha256": {p: sha(ROOT / p) for p in SOURCE_FILES},
        "cache_protocol": "per_query_verified_page_cache_cold_vs_full_file_warm",
        "timing_scope": "page-file open/header, page pruning, reads, exact filter, ID sort, close; resident directory",
        "modes": ["cold_page_cache", "warm_page_cache"],
    }
    return identity, tasks


def validate_metrics(path: Path, task: dict, repeats: int) -> list[dict]:
    rows = read_csv(path)
    oracle = {
        fields[0]: (int(fields[-2]), fields[-1])
        for fields in (line.split("\t") for line in task["oracle_tsv"].splitlines())
    }
    expected = {
        (q, str(r), mode)
        for q in task["query_ids"]
        for r in range(1, repeats + 1)
        for mode in ("cold_page_cache", "warm_page_cache")
    }
    actual = {(r["query_id"], r["repeat"], r["cache_mode"]) for r in rows}
    if actual != expected or len(rows) != len(expected):
        raise ValueError(f"incomplete/duplicate measurement matrix: {path}")
    for row in rows:
        resident, total = int(row["resident_pages_before"]), int(row["total_os_pages"])
        required = 0 if row["cache_mode"] == "cold_page_cache" else total
        elapsed = float(row["wall_seconds"])
        if (
            resident != required
            or total <= 0
            or not math.isfinite(elapsed)
            or elapsed <= 0
        ):
            raise ValueError(f"invalid residency or timing: {path}")
        if row["oracle_match"] != "true":
            raise ValueError(f"oracle mismatch: {path}")
        if (int(row["result_count"]), row["result_sha256"]) != oracle[row["query_id"]]:
            raise ValueError(f"result hash/count differs from frozen oracle: {path}")
        if int(row["logical_bytes"]) < 0 or int(row["logical_bytes"]) % 4096:
            raise ValueError(f"invalid logical bytes: {path}")
        if row["os_read_bytes"] and int(row["os_read_bytes"]) < 0:
            raise ValueError(f"invalid OS read counter: {path}")
    return rows


def summarize(output: Path, manifest: dict, tasks: list[dict]) -> None:
    summaries = []
    for task in tasks:
        key = f"{task['dataset_id']}__{task['layout_id']}"
        item = manifest["tasks"][key]
        path = output / item["metrics"]
        if sha(path) != item["metrics_sha256"]:
            raise ValueError(f"measured output checksum mismatch: {path}")
        rows = validate_metrics(path, task, manifest["identity"]["repeats"])
        for mode in manifest["identity"]["modes"]:
            selected = [r for r in rows if r["cache_mode"] == mode]
            by_query = defaultdict(list)
            for row in selected:
                by_query[row["query_id"]].append(float(row["wall_seconds"]))
            io = [int(r["os_read_bytes"]) for r in selected if r["os_read_bytes"]]
            summaries.append(
                {
                    "dataset_id": task["dataset_id"],
                    "layout_id": task["layout_id"],
                    "cache_mode": mode,
                    "queries": len(by_query),
                    "measured_rows": len(selected),
                    "mean_query_median_seconds": statistics.mean(
                        statistics.median(v) for v in by_query.values()
                    ),
                    "mean_logical_bytes": statistics.mean(
                        int(r["logical_bytes"]) for r in selected
                    ),
                    "mean_os_read_bytes": statistics.mean(io)
                    if len(io) == len(selected)
                    else "",
                    "os_read_bytes_available_rows": len(io),
                }
            )
    with (output / "summary.csv").open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--application-root",
        type=Path,
        default=ROOT / "experiments/outputs/application_query/full_benchmark",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "experiments/outputs/application_cache/full_benchmark",
    )
    parser.add_argument(
        "--probe-bin",
        type=Path,
        default=ROOT / "build/bench/src/cli/rch_application_cache_probe",
    )
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or not 1 <= args.repeats <= 1000 or args.seed < 0:
        parser.error("requires Linux, repeats in 1..1000, and a nonnegative seed")
    args.application_root = args.application_root.resolve()
    args.output_dir = args.output_dir.resolve()
    args.probe_bin = args.probe_bin.resolve()
    identity, tasks = prepare(args)
    # Plan is read-only, including when an output directory already exists.
    if not args.run and not args.validate_only:
        print(
            json.dumps(
                {
                    "status": "plan_only",
                    "identity": identity,
                    "layout_tasks": len(tasks),
                    "measurements": sum(len(t["query_ids"]) for t in tasks)
                    * args.repeats
                    * 2,
                    "output": str(args.output_dir),
                },
                indent=2,
            )
        )
        return 0
    output = args.output_dir
    manifest_path = output / "run_manifest.json"
    if args.resume or args.validate_only:
        manifest = json.loads(manifest_path.read_text())
        if manifest["identity"] != identity:
            raise ValueError(
                "resume/validation identity mismatch; sources, binary or configuration changed"
            )
    else:
        output.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema": "rch.application_cache",
            "status": "running",
            "identity": identity,
            "environment": {"platform": platform.platform(), "python": sys.version},
            "created_utc": datetime.now(UTC).isoformat(),
            "tasks": {},
        }
        write_json(manifest_path, manifest)
    if args.validate_only:
        if manifest["status"] != "completed" or len(manifest["tasks"]) != len(tasks):
            raise ValueError("run is not complete")
        if (
            sha(output / "application_source_manifest.json")
            != identity["application_manifest_sha256"]
        ):
            raise ValueError("frozen application snapshot checksum mismatch")
        for item in manifest["tasks"].values():
            if item["status"] != "passed":
                raise ValueError("not every task passed")
        if sha(output / "summary.csv") != manifest["summary_sha256"]:
            raise ValueError("summary checksum mismatch")
        # Validate without rewriting measured artifacts.
        for task in tasks:
            item = manifest["tasks"][f"{task['dataset_id']}__{task['layout_id']}"]
            path = output / item["metrics"]
            if sha(path) != item["metrics_sha256"]:
                raise ValueError("metrics checksum mismatch")
            validate_metrics(path, task, args.repeats)
        print(json.dumps({"status": "passed", "tasks": len(tasks)}))
        return 0
    if not args.resume:
        snapshot = output / "application_source_manifest.json"
        snapshot.write_bytes((args.application_root / "run_manifest.json").read_bytes())
        manifest["application_source_snapshot_sha256"] = sha(snapshot)
        manifest["environment"]["mountinfo"] = Path("/proc/self/mountinfo").read_text()
        write_json(manifest_path, manifest)
    if (
        sha(output / "application_source_manifest.json")
        != identity["application_manifest_sha256"]
    ):
        raise ValueError("frozen application snapshot checksum mismatch")
    for number, task in enumerate(tasks):
        key = f"{task['dataset_id']}__{task['layout_id']}"
        old = manifest["tasks"].get(key, {})
        if old.get("status") == "passed":
            if sha(output / old["metrics"]) != old["metrics_sha256"]:
                raise ValueError(f"completed task checksum mismatch: {key}")
            validate_metrics(output / old["metrics"], task, args.repeats)
            continue
        attempt = old.get("attempt", 0) + 1
        tsv = output / f"{key}.oracle.tsv"
        tsv.write_text(task["oracle_tsv"])
        metrics = output / f"{key}.attempt{attempt}.csv"
        command = [
            str(args.probe_bin),
            task["page"],
            task["index"],
            str(tsv),
            str(args.repeats),
            str(metrics),
            str(int(task["layout_id"] == "A0_full_scan")),
            str(args.seed + number),
        ]
        item = {
            "status": "running",
            "attempt": attempt,
            "command": command,
            "metrics": metrics.name,
            "page_sha256": task["page_sha256"],
            "index_sha256": task["index_sha256"],
            "oracle_sha256": task["oracle_sha256"],
            "query_sha256": task["query_sha256"],
            "attempts": old.get("attempts", []),
        }
        manifest["tasks"][key] = item
        manifest["status"] = "running"
        write_json(manifest_path, manifest)
        print(f"START {key} attempt={attempt}", flush=True)
        log = output / f"{key}.attempt{attempt}.log"
        with log.open("w") as log_output:
            result = subprocess.run(
                command, check=False, stdout=log_output, stderr=subprocess.STDOUT
            )
        item["attempts"].append(
            {"attempt": attempt, "returncode": result.returncode, "log": log.name}
        )
        item["status"] = "failed" if result.returncode else "validating"
        if result.returncode:
            manifest["status"] = "failed"
            write_json(manifest_path, manifest)
            raise RuntimeError(
                f"{key} failed; see {log}; use --run --resume after resolving the cause"
            )
        validate_metrics(metrics, task, args.repeats)
        item["status"] = "passed"
        item["metrics_sha256"] = sha(metrics)
        write_json(manifest_path, manifest)
    summarize(output, manifest, tasks)
    final_identity, _ = prepare(args)
    if final_identity != identity:
        raise ValueError("sources or executable changed during measurement")
    manifest["summary_sha256"] = sha(output / "summary.csv")
    manifest["status"] = "completed"
    write_json(manifest_path, manifest)
    print(json.dumps({"status": "completed", "tasks": len(tasks)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"application cache experiment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
