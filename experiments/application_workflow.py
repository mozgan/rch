"""Frozen protocol, independent result oracle, and workflow evidence validation."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "rch.application_workflow.v1"
LAYOUTS = ("A0_input", "A3_isotropic_hilbert", "A6_rch_C3")
COUNTS = (256, 512, 1024)
PHASES = ("read_seconds", "order_seconds", "prepare_seconds", "query_write_seconds", "sync_seconds")
BULK_FILES = ("order.csv", "points.page", "points.index", "results.bin")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def protocol():
    return {
        "measurement": "one continuous C++ steady-clock interval per fresh process",
        "stages": ["read/parse prepared XYZ", "one order_point_cloud call, refinement off",
                   "write order/page/index files", "load directory, execute frozen queries, write all result IDs",
                   "fsync order/page/index/results files and output directory"],
        "input_cache": "full-file warm verified with mincore before timer and I/O snapshots",
        "page_cache": "natural newly written file state; no cold-query intervention",
        "excluded": ["download/conversion", "oracle generation/load", "input warming",
                     "process startup", "output directory creation", "post-timer verification",
                     "metrics/provenance output", "work-file cleanup"],
        "io": "Linux process-attributed read_bytes/write_bytes deltas over the complete interval; null if unavailable",
        "workload": "nested prefixes of distinct seeded 256-window blocks; 86 small, 85 medium, 85 large per block",
        "result_format": "RCHWF001, u64 query count, then per-query u64 result count and ascending u64 raw IDs; little-endian",
        "scope": "fixed storage/query workflow, not a downstream reconstruction/classification pipeline",
    }


def freeze_workloads(points, counts, output, seed=2026):
    """Build once, independently of layouts/repeats; reuse the exact 256-window recipe."""
    import numpy as np
    from experiments.runners.run_application_query_smoke import write_full_query_matrix

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    xyz = np.asarray(points, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) == 0 or not np.isfinite(xyz).all():
        raise ValueError("oracle input must be a nonempty finite N x 3 cloud")
    counts = tuple(counts)
    if not counts or len(set(counts)) != len(counts) or min(counts) < 1 or max(counts) > 1024:
        raise ValueError("invalid workload sizes")
    windows = []
    for block in range((max(counts) + 255) // 256):
        path = output / f"block_{block}.csv"
        write_full_query_matrix(path, points, seed + block)
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                row["query_id"] = f"b{block}_" + row["query_id"]
                windows.append(row)
    windows = windows[:max(counts)]
    hashes = {}
    total_ids = dict.fromkeys(counts, 0)
    for count in counts:
        hashes[count] = hashlib.sha256(b"RCHWF001" + struct.pack("<Q", count))
    lines = []
    for index, query in enumerate(windows):
        lo = [float(query[k]) for k in ("min_x", "min_y", "min_z")]
        hi = [float(query[k]) for k in ("max_x", "max_y", "max_z")]
        mask = np.ones(len(xyz), dtype=bool)
        for axis in range(3):
            mask &= (xyz[:, axis] >= lo[axis]) & (xyz[:, axis] <= hi[axis])
        ids = np.flatnonzero(mask).astype("<u8").tobytes()
        result_count = len(ids) // 8
        fields = [query[k] for k in ("query_id", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z")]
        lines.append("\t".join(fields + [str(result_count), hashlib.sha256(ids).hexdigest()]))
        for count in counts:
            if index < count:
                hashes[count].update(struct.pack("<Q", result_count))
                hashes[count].update(ids)
                total_ids[count] += result_count
    result = {}
    for count in counts:
        path = output / f"queries_{count}.tsv"
        path.write_text("\n".join(lines[:count]) + "\n")
        result[str(count)] = {"path": str(path.relative_to(output.parent)), "sha256": digest(path),
                              "query_count": count, "result_sha256": hashes[count].hexdigest(),
                              "result_ids": total_ids[count], "result_bytes": 16 + 8 * count + 8 * total_ids[count]}
    return result


def checked(root, record):
    path = (root / record["path"]).resolve()
    path.relative_to(root.resolve())
    if digest(path) != record["sha256"]:
        raise ValueError(f"workflow checksum mismatch: {path}")
    return path


def validate_metrics(value, layout, point_count, workload):
    if (value.get("schema") != "rch.application_workflow.metrics.v1" or
            value.get("layout") != layout or value.get("point_count") != point_count or
            value.get("query_count") != workload["query_count"] or
            value.get("ordering_calls") != 1 or value.get("oracle_match") is not True or
            value.get("input_warm_verified") is not True or
            value.get("result_ids") != workload["result_ids"]):
        raise ValueError("workflow metrics configuration/oracle mismatch")
    for name in (*PHASES, "total_seconds", "cpu_seconds"):
        if not isinstance(value.get(name), (float, int)) or not math.isfinite(value[name]) or value[name] < 0:
            raise ValueError("invalid workflow timing")
    if value["total_seconds"] <= 0 or not math.isclose(sum(value[k] for k in PHASES), value["total_seconds"], rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError("workflow phases do not partition continuous time")
    for name in ("logical_query_bytes", "result_ids", "peak_rss_kib", "storage_read_bytes", "storage_write_bytes"):
        x = value.get(name)
        if x is None and name.startswith("storage_"):
            continue
        if not isinstance(x, int) or x < 0:
            raise ValueError("invalid workflow byte/count field")
    if value["logical_query_bytes"] % 4096 or len(value.get("order_sha256", "")) != 64:
        raise ValueError("invalid logical bytes or order hash")


def validate_run(root):
    """Portable stored-result validation; does not open or execute measured binaries."""
    root = Path(root).resolve()
    manifest = json.loads((root / "run_manifest.json").read_text())
    if manifest["schema"] != SCHEMA or manifest["status"] != "completed" or manifest["protocol"] != protocol():
        raise ValueError("incomplete or unsupported workflow protocol")
    if set(manifest["source_snapshots"]) != set(manifest["identity"]["source_sha256"]):
        raise ValueError("workflow source snapshot coverage mismatch")
    for name, record in manifest["source_snapshots"].items():
        if record["sha256"] != manifest["identity"]["source_sha256"][name]:
            raise ValueError("workflow source snapshot identity mismatch")
    for record in manifest["source_snapshots"].values():
        checked(root, record)
    if manifest.get("build_cache"):
        checked(root, manifest["build_cache"])
    config = manifest["config"]
    if (not config["datasets"] or len(set(config["datasets"])) != len(config["datasets"])
            or config["layouts"] != list(LAYOUTS) or not config["query_counts"]
            or len(set(config["query_counts"])) != len(config["query_counts"])
            or not set(config["query_counts"]) <= set(COUNTS)
            or not isinstance(config["repeats"], int) or not 1 <= config["repeats"] <= 1000):
        raise ValueError("invalid workflow configuration")
    expected = {(d, int(q), r, layout) for d in config["datasets"] for q in config["query_counts"]
                for r in range(1, config["repeats"] + 1) for layout in config["layouts"]}
    actual = set()
    samples = []
    for dataset in manifest["datasets"]:
        checked(root, dataset["input"])
        if set(dataset["workloads"]) != {str(q) for q in config["query_counts"]}:
            raise ValueError("workflow query-count coverage mismatch")
        previous = []
        for count in sorted(config["query_counts"]):
            workload = dataset["workloads"][str(count)]
            lines = checked(root, workload).read_text().splitlines()
            if workload["query_count"] != count or len(lines) != count or lines[:len(previous)] != previous:
                raise ValueError("workflow query prefixes/coverage differ")
            if len({line.split("\t")[0] for line in lines}) != count:
                raise ValueError("duplicate workflow query IDs")
            previous = lines
    datasets = {d["dataset_id"]: d for d in manifest["datasets"]}
    if set(datasets) != set(config["datasets"]) or len(datasets) != len(manifest["datasets"]):
        raise ValueError("workflow dataset coverage mismatch")
    order_hashes = {}
    for trial in manifest["trials"]:
        key = (trial["dataset_id"], trial["query_count"], trial["repeat"], trial["layout"])
        if key in actual or key not in expected or trial["status"] != "passed":
            raise ValueError("duplicate, unexpected, or failed workflow trial")
        actual.add(key)
        value = json.loads(checked(root, trial["metrics"]).read_text())
        dataset = datasets[key[0]]
        workload = dataset["workloads"][str(key[1])]
        validate_metrics(value, key[3], dataset["point_count"], workload)
        result = trial["outputs"]["results.bin"]
        if set(trial["outputs"]) != set(BULK_FILES):
            raise ValueError("workflow output inventory mismatch")
        if result["sha256"] != workload["result_sha256"] or result["bytes"] != workload["result_bytes"]:
            raise ValueError("materialized workflow results differ from independent oracle")
        for record in trial["outputs"].values():
            (root / record["path"]).resolve().relative_to(root)
            if (not isinstance(record["retained"], bool) or record["bytes"] <= 0
                    or record["retained"] != config["keep_work_files"]):
                raise ValueError("invalid workflow output record")
            if record["retained"]:
                checked(root, record)
        order_key = (key[0], key[3])
        if order_hashes.setdefault(order_key, value["order_sha256"]) != value["order_sha256"]:
            raise ValueError("workflow order changed across repeats or query counts")
        samples.append({**value, "dataset_id": key[0], "query_count": key[1], "repeat": key[2], "layout": key[3]})
    if actual != expected:
        raise ValueError("missing workflow trials")
    return manifest, samples
