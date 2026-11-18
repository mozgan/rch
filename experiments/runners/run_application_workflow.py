#!/usr/bin/env python3
"""Resumable storage/query workflows; no timing, dataset download, or oracle in analysis."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_workflow import (
    BULK_FILES, COUNTS, LAYOUTS, SCHEMA, checked, digest, freeze_workloads,
    protocol, validate_metrics, validate_run, write_json,
)


def source_files():
    return sorted({
        "src/cli/rch_application_workflow.cpp", "src/cli/CMakeLists.txt",
        "CMakeLists.txt", "cmake/ReproducibleBuild.cmake",
        "experiments/application_workflow.py", "experiments/runners/run_application_workflow.py",
        "experiments/runners/run_application_query_smoke.py", "experiments/runners/run_real_datasets.py",
        "data/synthetic/generators/common.py", "scripts/convert_dataset.py",
        "CMakePresets.json",
        *[str(p.relative_to(ROOT)) for p in (ROOT / "cmake").rglob("*.cmake")],
        *[str(p.relative_to(ROOT)) for p in (ROOT / "include/rch").rglob("*.hpp")],
        *[str(p.relative_to(ROOT)) for p in (ROOT / "data/manifests").rglob("*.yml")],
    })


def prepare_real(dataset_id, output, counts, seed):
    from data.synthetic.generators.common import write_xyz_csv
    from experiments.runners.run_application_query_smoke import load_dataset_provenance
    data = load_dataset_provenance(dataset_id, ROOT / "data/raw/stanford_3d_scanning",
                                   ROOT / "data/processed/stanford_3d_scanning")
    points = data.pop("points")
    base = output / "inputs" / dataset_id
    base.mkdir(parents=True, exist_ok=True)
    path = base / "points.csv"
    write_xyz_csv(path, points)
    workloads = freeze_workloads(points, counts, base / "workloads", seed)
    for workload in workloads.values():
        workload["path"] = str((base / workload["path"]).relative_to(output))
    return {"dataset_id": dataset_id, "point_count": len(points), "provenance": data,
            "input": {"path": str(path.relative_to(output)), "sha256": digest(path)},
            "workloads": workloads}


def run(args, prepare_dataset=prepare_real):
    output = args.output_dir.resolve()
    binary = args.binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(f"workflow executable missing: {binary}")
    config = {"datasets": args.dataset, "query_counts": args.query_counts,
              "layouts": list(LAYOUTS), "repeats": args.repeats, "seed": args.seed,
              "keep_work_files": args.keep_work_files}
    current = {name: digest(ROOT / name) for name in source_files()}
    identity = {"binary_sha256": digest(binary), "source_sha256": current}
    path = output / "run_manifest.json"
    if args.resume:
        manifest = json.loads(path.read_text())
        if manifest["schema"] != SCHEMA or manifest["config"] != config or manifest["identity"] != identity:
            raise ValueError("workflow resume identity/configuration mismatch")
        for record in manifest["source_snapshots"].values():
            checked(output, record)
    else:
        output.mkdir(parents=True, exist_ok=False)
        snapshots = {}
        for name, checksum in current.items():
            dest = output / "sources" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
            snapshots[name] = {"path": str(dest.relative_to(output)), "sha256": checksum}
        manifest = {"schema": SCHEMA, "status": "preparing", "config": config,
                    "protocol": protocol(), "identity": identity, "source_snapshots": snapshots,
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "environment": {"platform": platform.platform(), "python": sys.version,
                                    "processor": platform.processor(), "logical_cpus": os.cpu_count(),
                                    "cpu_affinity": sorted(os.sched_getaffinity(0)),
                                    "mountinfo": Path("/proc/self/mountinfo").read_text()},
                    "datasets": [], "trials": []}
        cache = binary.parents[2] / "CMakeCache.txt"
        if cache.is_file():
            shutil.copyfile(cache, output / "build_cache.txt")
            manifest["build_cache"] = {"path": "build_cache.txt", "sha256": digest(output / "build_cache.txt")}
        write_json(path, manifest)
    try:
        for dataset_id in config["datasets"]:
            dataset = next((d for d in manifest["datasets"] if d["dataset_id"] == dataset_id), None)
            if dataset is None:
                print(f"PREPARE {dataset_id}: input conversion and independent oracle (outside timers)", flush=True)
                dataset = prepare_dataset(dataset_id, output, config["query_counts"], args.seed)
                manifest["datasets"].append(dataset)
                write_json(path, manifest)
            checked(output, dataset["input"])
            for workload in dataset["workloads"].values():
                checked(output, workload)
            for repeat in range(1, args.repeats + 1):
                schedule = [(q, layout) for q in args.query_counts for layout in LAYOUTS]
                random.Random(f"workflow-v1:{args.seed}:{dataset_id}:{repeat}").shuffle(schedule)
                for count, layout in schedule:
                    key = (dataset_id, count, repeat, layout)
                    trial = next((t for t in manifest["trials"]
                                  if (t["dataset_id"], t["query_count"], t["repeat"], t["layout"]) == key), None)
                    workload = dataset["workloads"][str(count)]
                    if trial and trial["status"] == "passed":
                        value = json.loads(checked(output, trial["metrics"]).read_text())
                        validate_metrics(value, layout, dataset["point_count"], workload)
                        for record in trial["outputs"].values():
                            if record["retained"]:
                                checked(output, record)
                        print("SKIP", key, flush=True)
                        continue
                    if trial is None:
                        trial = {"dataset_id": dataset_id, "query_count": count, "repeat": repeat,
                                 "layout": layout, "attempt": 0}
                        manifest["trials"].append(trial)
                    trial["attempt"] += 1
                    work = output / "runs" / dataset_id / f"q{count}" / f"r{repeat}" / layout / f"attempt{trial['attempt']}"
                    work.parent.mkdir(parents=True, exist_ok=True)
                    log = work.with_suffix(".log")
                    trial.update(status="running", log=str(log.relative_to(output)))
                    manifest["status"] = "running"
                    write_json(path, manifest)
                    command = [str(binary), str(output / dataset["input"]["path"]),
                               str(output / workload["path"]), layout, str(work)]
                    print("START", key, "attempt", trial["attempt"], flush=True)
                    begin = perf_counter()
                    with log.open("w") as stream:
                        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT)
                    trial["process_seconds_including_validation"] = perf_counter() - begin
                    metrics = work / "metrics.json"
                    value = json.loads(metrics.read_text())
                    validate_metrics(value, layout, dataset["point_count"], workload)
                    trial["metrics"] = {"path": str(metrics.relative_to(output)), "sha256": digest(metrics)}
                    outputs = {name: {"path": str((work / name).relative_to(output)),
                                      "sha256": digest(work / name), "bytes": (work / name).stat().st_size,
                                      "retained": args.keep_work_files} for name in BULK_FILES}
                    if (outputs["results.bin"]["sha256"] != workload["result_sha256"] or
                            outputs["results.bin"]["bytes"] != workload["result_bytes"]):
                        raise ValueError("workflow materialized IDs differ from independent Python oracle")
                    trial.update(outputs=outputs, status="passed")
                    if not args.keep_work_files:
                        for name in BULK_FILES:
                            (work / name).unlink()
                    write_json(path, manifest)
                    print(f"PASS {key}: continuous={value['total_seconds']:.6f}s", flush=True)
        if digest(binary) != identity["binary_sha256"] or any(digest(ROOT / n) != h for n, h in current.items()):
            raise ValueError("workflow binary/sources changed during measurement")
        manifest["status"] = "completed"
        write_json(path, manifest)
        validate_run(output)
    except BaseException:
        manifest["status"] = "failed"
        write_json(path, manifest)
        raise
    print(f"Completed {len(manifest['trials'])} workflows; manifest: {path}", flush=True)


def main():
    from experiments.runners.run_application_query_smoke import DEFAULT_DATASET_IDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "build/bench/src/cli/rch_application_workflow")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/outputs/application_workflow/full_benchmark")
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--query-counts", nargs="+", type=int, default=list(COUNTS))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--keep-work-files", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.run and platform.system() != "Linux":
        parser.error("workflow measurement requires Linux; stored-result validation is portable")
    args.dataset = args.dataset or list(DEFAULT_DATASET_IDS)
    if (len(set(args.dataset)) != len(args.dataset) or not set(args.dataset) <= set(DEFAULT_DATASET_IDS)
            or len(set(args.query_counts)) != len(args.query_counts) or not set(args.query_counts) <= set(COUNTS)
            or not 1 <= args.repeats <= 1000 or args.seed < 0):
        parser.error("requires unique known datasets, query counts from 256/512/1024, positive repeats and nonnegative seed")
    if args.validate_only:
        if args.run or args.resume:
            parser.error("--validate-only cannot execute or resume")
        manifest, samples = validate_run(args.output_dir)
        print(json.dumps({"status": "passed", "trials": len(samples), "config": manifest["config"]}))
    elif args.run:
        run(args)
    elif args.resume:
        parser.error("resume requires --run")
    else:
        print(json.dumps({"status": "plan_only", "workflow_runs": len(args.dataset) * len(args.query_counts) * 3 * args.repeats,
                          "measured_queries": len(args.dataset) * sum(args.query_counts) * 3 * args.repeats,
                          "protocol": protocol()}, indent=2))


if __name__ == "__main__":
    main()
