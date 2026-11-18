#!/usr/bin/env python3
"""Validate complete application runs and report paired, dataset-specific effects."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS = (
    "stanford_bunny",
    "stanford_armadillo",
    "stanford_dragon",
    "usgs_cameron_peak",
    'noaa_santiam_river',
    'noaa_long_island',
    'noaa_southwest_florida',
)
sys.path.insert(0, str(REPO_ROOT))
from experiments.application_layouts import (
    LAYOUTS,
    NATIVE_LAYOUTS,
    RULES,
    expected_layouts,
)



def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_mean_ci(
    values: list[float], seed: int, samples: int = 10000
) -> tuple[float, float]:
    rng = random.Random(seed)
    means = [
        statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)
    ]
    return percentile(means, 0.025), percentile(means, 0.975)


def verify_file(path: str, checksum: str) -> None:
    target = (REPO_ROOT / path).resolve()
    target.relative_to(REPO_ROOT)
    if digest(target) != checksum:
        raise ValueError(f"checksum mismatch: {path}")


def validate_manifest(
    root: Path, queries: int, repeats: int, datasets: tuple[str, ...]
) -> dict[str, Any]:
    manifest = json.loads((root / "run_manifest.json").read_text())
    layouts = expected_layouts(manifest)
    records = manifest["datasets"]
    ids = [d["dataset_id"] for d in records]
    if (
        len(set(ids)) != len(ids)
        or set(ids) != set(datasets)
        or set(manifest["expected_dataset_ids"]) != set(datasets)
    ):
        raise ValueError("missing, duplicate or unexpected dataset")
    if set(manifest["ordering"]["layouts"]) != set(layouts) or len(
        manifest["ordering"]["layouts"]
    ) != len(layouts):
        raise ValueError("layout protocol mismatch")
    if (
        manifest["query_count_per_dataset_layout"] != queries
        or manifest["cache_protocol"]["measured_workload_repeats"] != repeats
    ):
        raise ValueError("query/repeat protocol mismatch")
    if manifest["compression_protocol"] is None:
        raise ValueError("compression protocol is missing")
    for d in records:
        for evidence in d.get("metadata_evidence", []):
            verify_file(evidence["path"], evidence["sha256"])
        if "source_manifest" in d:
            verify_file(d["source_manifest"], d["source_manifest_sha256"])
        for path, checksum in [
            ("archive", "archive_sha256"),
            ("processed_file", "processed_sha256"),
            ("preprocessing_manifest", "preprocessing_manifest_sha256"),
            ("input_csv", "input_csv_sha256"),
        ]:
            verify_file(d[path], d[checksum])
        if "query_workload" in d:
            verify_file(d["query_workload"]["file"], d["query_workload"]["file_sha256"])
        for value in d["query_results"].values():
            verify_file(value["path"], value["sha256"])
        verify_file(
            d["warm_cache_query_metrics"]["path"],
            d["warm_cache_query_metrics"]["sha256"],
        )
        for value in d["order_files"].values():
            verify_file(value["path"], value["sha256"])
            verify_file(value["manifest_path"], value["manifest_sha256"])
        for value in d["storage_integrity"].values():
            for path, checksum in [
                ("manifest", "manifest_sha256"),
                ("page_file", "page_file_sha256"),
                ("index_file", "index_file_sha256"),
                ("query_memory_file", "query_memory_sha256"),
            ]:
                verify_file(value[path], value[checksum])
        if set(d["compression"]) != set(layouts):
            raise ValueError("compression matrix incomplete")
        for value in d["compression"].values():
            verify_file(value["compressed_file"], value["compressed_sha256"])
        if set(d.get("layout_schedule", [])) != set(layouts) or len(
            d["layout_schedule"]
        ) != len(layouts):
            raise ValueError("missing/duplicate layout execution schedule")
        if set(d["order_files"]) != set(layouts) or set(
            d["storage_integrity"]
        ) != set(layouts):
            raise ValueError("native layout provenance matrix incomplete")
        for layout in layouts:
            meta = json.loads(
                (REPO_ROOT / d["order_files"][layout]["manifest_path"]).read_text()
            )
            if (
                d["ordering_diagnostics"][layout] != meta
                or int(meta["point_count"]) != d["point_count"]
            ):
                raise ValueError("ordering diagnostic snapshot mismatch")
            if RULES[layout]["bit_allocator"] is None:
                continue
            if (
                meta.get("bit_allocator") != RULES[layout]["bit_allocator"]
                or meta.get("refinement") != "off"
                or meta.get("controlled_frame_quantizer")
            ):
                raise ValueError(
                    "ordering manifest does not implement the declared native rule"
                )
            if (
                meta.get("fixed_frame_domain_half_extent", 0) != 0
                or int(meta["uniform_bits"]) != 10
                or int(meta["min_axis_bits"]) != 1
            ):
                raise ValueError("unexpected fixed-domain/depth parameters")
            expected_method = (
                "isotropic_hilbert" if layout == "A3_isotropic_hilbert" else "rch"
            )
            expected_frame = (
                "none" if layout == "A3_isotropic_hilbert" else "det_mcd"
            )
            if (
                meta.get("method") != expected_method
                or meta.get("frame_estimator") != expected_frame
            ):
                raise ValueError("native layout method/frame mismatch")
            bits = meta["bits_axis"]
            if (
                len(bits) != 3
                or any(type(b) is not int or not 1 <= b <= 32 for b in bits)
                or sum(bits) > 63
            ):
                raise ValueError("invalid resolved bit budget")
            if layout in ("A3_isotropic_hilbert", "A6_rch") and bits != [
                10,
                10,
                10,
            ]:
                raise ValueError("C0 reference changed resolution")
            for key in (
                "domain_clipped_point_count",
                "duplicate_hilbert_key_point_count",
                "frame_core_outside_point_count",
            ):
                count = meta["quantization_diagnostics"][key]
                if type(count) is not int or not 0 <= count <= d["point_count"]:
                    raise ValueError("invalid native quantization diagnostic")
    return manifest


def analyze(
    root: Path,
    output: Path,
    expected_queries: int = 256,
    expected_repeats: int = 5,
    expected_datasets: tuple[str, ...] = DATASETS,
) -> dict[str, Any]:
    manifest = validate_manifest(
        root, expected_queries, expected_repeats, expected_datasets
    )
    layouts = expected_layouts(manifest)
    groups: dict[tuple[str, str], dict[tuple[str, int], dict[str, str]]] = {}
    summaries, pairs = [], []
    for d in manifest["datasets"]:
        dataset = d["dataset_id"]
        windows = d["query_results"]["query_windows.csv"]["path"]
        with (REPO_ROOT / windows).open(newline="") as handle:
            query_ids = [r["query_id"] for r in csv.DictReader(handle)]
        if (
            len(query_ids) != expected_queries
            or len(set(query_ids)) != expected_queries
        ):
            raise ValueError("query window IDs are not complete/unique")
        if expected_queries == 256:
            expected_ids = {
                f"{label}_{i:03d}"
                for label, count in (("small", 86), ("medium", 85), ("large", 85))
                for i in range(count)
            }
            if set(query_ids) != expected_ids or d["query_workload"]["seed"] != 2026:
                raise ValueError("frozen query groups/seed do not match")
            with (REPO_ROOT / d["query_workload"]["file"]).open(newline="") as handle:
                input_windows = list(csv.DictReader(handle))
            with (REPO_ROOT / windows).open(newline="") as handle:
                output_windows = list(csv.DictReader(handle))
            if len(input_windows) != len(output_windows):
                raise ValueError("executor query file differs from frozen input")
            for given, used in zip(input_windows, output_windows):
                if given["query_id"] != used["query_id"] or any(
                    float(given[field]) != float(used[field])
                    for field in given
                    if field != "query_id"
                ):
                    raise ValueError(
                        "executor query coordinates differ from frozen input"
                    )
        expected_keys = set(
            itertools.product(query_ids, range(1, expected_repeats + 1))
        )
        with (REPO_ROOT / d["query_results"]["query_results.csv"]["path"]).open(
            newline=""
        ) as handle:
            correctness = list(csv.DictReader(handle))
        observed_schedule = list(dict.fromkeys(r["layout_id"] for r in correctness))
        if observed_schedule != d["layout_schedule"]:
            raise ValueError(
                "executor layout schedule differs from recorded schedule"
            )
        signatures: dict[str, tuple[str, str]] = {}
        seen_correctness = set()
        for r in correctness:
            key = (r["layout_id"], r["query_id"])
            if (
                r["dataset_id"] != dataset
                or key in seen_correctness
                or r["oracle_match"] != "true"
            ):
                raise ValueError("invalid correctness result")
            seen_correctness.add(key)
            signature = (r["result_count"], r["result_ids_sha256"])
            if signatures.setdefault(r["query_id"], signature) != signature:
                raise ValueError("result count/hash differs across layouts")
        if seen_correctness != set(itertools.product(layouts, query_ids)):
            raise ValueError("correctness matrix incomplete")
        with (REPO_ROOT / d["warm_cache_query_metrics"]["path"]).open(
            newline=""
        ) as handle:
            metrics = list(csv.DictReader(handle))
        for r in metrics:
            key, sample = (dataset, r["layout_id"]), (r["query_id"], int(r["repeat"]))
            if (
                r["dataset_id"] != dataset
                or r["layout_id"] not in layouts
                or sample in groups.setdefault(key, {})
            ):
                raise ValueError("duplicate/unexpected measured row")
            if r["oracle_match"] != "true" or (
                r["result_count"],
                r["result_ids_sha256"],
            ) != signatures.get(r["query_id"]):
                raise ValueError("measured results differ from correctness oracle")
            for field in (
                "wall_seconds",
                "cpu_seconds",
                "logical_bytes_read",
                "pages_read",
                "candidate_pages",
                "records_examined",
                "selectivity",
            ):
                if not math.isfinite(float(r[field])) or float(r[field]) < 0:
                    raise ValueError(f"invalid {field}")
            if int(r["logical_bytes_read"]) != int(r["pages_read"]) * 4096:
                raise ValueError("logical byte/page mismatch")
            if not (
                int(r["result_count"])
                <= int(r["records_examined"])
                <= int(r["pages_read"]) * 128
            ):
                raise ValueError("invalid examined record count")
            if (
                r["layout_id"] == "A0_full_scan"
                and int(r["pages_read"])
                != d["storage_integrity"]["A0_full_scan"]["page_count"]
            ):
                raise ValueError("full scan did not read all pages")
            if not math.isclose(
                float(r["selectivity"]),
                int(r["result_count"]) / d["point_count"],
                rel_tol=1e-10,
                abs_tol=1e-12,
            ):
                raise ValueError("invalid selectivity")
            groups[key][sample] = r
        means: dict[str, list[float]] = {}
        for layout in layouts:
            current = groups.get((dataset, layout), {})
            if set(current) != expected_keys:
                raise ValueError(f"incomplete measured matrix: {dataset}/{layout}")
            means[layout] = [
                statistics.fmean(
                    float(current[(q, repeat)]["wall_seconds"])
                    for repeat in range(1, expected_repeats + 1)
                )
                for q in query_ids
            ]
            values = [float(r["wall_seconds"]) for r in current.values()]
            storage, compressed = (
                d["storage_integrity"][layout],
                d["compression"][layout],
            )
            meta = d.get("ordering_diagnostics", {}).get(layout, {})
            quant = meta.get("quantization_diagnostics", {})
            fitted = meta.get("fitted_frame_diagnostics") or {}

            def fraction(key):
                return quant[key] / d["point_count"] if key in quant else None

            summaries.append(
                {
                    "dataset_id": dataset,
                    "layout_id": layout,
                    "rows": len(values),
                    "bit_rule": RULES[layout]["bit_rule"],
                    "bit_allocator": RULES[layout]["bit_allocator"],
                    "resolved_bits_axis": json.dumps(meta.get("bits_axis")),
                    "domain_half_extents": json.dumps(
                        meta.get("frame_domain_half_extents")
                    ),
                    "frame_mode": fitted.get("mode"),
                    "robust_fallback_used": meta.get("robust_fallback_used"),
                    "clipped_fraction": fraction("domain_clipped_point_count") if layout.startswith("A6_") else None,
                    "outside_core_fraction": fraction("frame_core_outside_point_count") if layout.startswith("A6_") else None,
                    "duplicate_key_fraction": fraction(
                        "duplicate_hilbert_key_point_count"
                    ),
                    "mean_query_wall_seconds": statistics.fmean(values),
                    **{
                        f"p{p}_wall_seconds": percentile(values, p / 100)
                        for p in (50, 95, 99)
                    },
                    **{
                        f"mean_{f}": statistics.fmean(
                            float(r[f]) for r in current.values()
                        )
                        for f in (
                            "cpu_seconds",
                            "pages_read",
                            "candidate_pages",
                            "logical_bytes_read",
                            "records_examined",
                            "selectivity",
                        )
                    },
                    "page_pruning_fraction": 1
                    - statistics.fmean(float(r["pages_read"]) for r in current.values())
                    / storage["page_count"],
                    "storage_bytes": storage["page_file_bytes"]
                    + storage["index_file_bytes"],
                    "compressed_payload_bytes": compressed["compressed_bytes"],
                    "compression_ratio": compressed["compression_ratio"],
                    "process_read_bytes_available_rows": sum(
                        r["process_read_bytes_delta"] != "" for r in current.values()
                    ),
                    "process_read_bytes_total": sum(
                        int(r["process_read_bytes_delta"])
                        for r in current.values()
                        if r["process_read_bytes_delta"] != ""
                    ),
                    "process_peak_rss_kib_after_query": storage["query_memory"][
                        "peak_rss_kib"
                    ],
                    "preparation_seconds": d["amortizable_preparation_seconds"][layout],
                }
            )
        comparisons = [
            ("A3_isotropic_hilbert", "A0_input"),
            ("A6_rch", "A0_input"),
            ("A6_rch", "A3_isotropic_hilbert"),
            ("A0_input", "A0_full_scan"),
            ("A6_rch", "A0_full_scan"),
        ]
        comparisons += [
            (layout, reference)
            for layout in NATIVE_LAYOUTS
            if layout in layouts
            for reference in (
                "A0_input",
                "A0_full_scan",
                "A3_isotropic_hilbert",
                "A6_rch",
            )
        ]
        if "A6_rch_C3" in layouts:
            comparisons += [
                (layout, "A6_rch_C3") for layout in ("A6_rch_C2", "A6_rch_C4")
            ]
        for layout, reference in comparisons:
            delta = [a - b for a, b in zip(means[layout], means[reference])]
            low, high = bootstrap_mean_ci(delta, 2026 + len(pairs))
            extra = (
                d["amortizable_preparation_seconds"][layout]
                - d["amortizable_preparation_seconds"][reference]
            )
            saving = -statistics.fmean(delta)
            pairs.append(
                {
                    "dataset_id": dataset,
                    "layout_id": layout,
                    "reference": reference,
                    "mean_delta_seconds": statistics.fmean(delta),
                    "ci95_low_seconds": low,
                    "ci95_high_seconds": high,
                    "extra_preparation_seconds": extra,
                    "break_even_queries": max(0, extra) / saving
                    if saving > 0
                    else None,
                    "interpretation": "conditional on observed workload; no positive query saving"
                    if saving <= 0
                    else "query saving observed; preparation uncertainty not included",
                }
            )
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in [("summary", summaries), ("paired_comparisons", pairs)]:
        with (output / f"{name}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = {
        "schema": "rch.application_query_analysis.v3"
        if len(layouts) > 4
        else "rch.application_query_analysis.v2",
        "layouts": list(layouts),
        "input_manifest_sha256": digest(root / "run_manifest.json"),
        "analyzer_sha256": digest(Path(__file__)),
        "dataset_count": len(manifest["datasets"]),
        "paired_unit": "query ID within dataset; repeats averaged first",
        "bootstrap_samples": 10000,
        "inference_scope": "within fixed dataset workload; no population or stability requirement claim",
        "rss_scope": "cumulative process high-water mark; previous layouts and oracle included",
        "preparation_scope": "median ordering-call time plus page and directory write/build; no durable fsync; excludes validation and repeated measurement cost",
        "summaries": summaries,
        "paired_comparisons": pairs,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-queries", type=int, default=256)
    parser.add_argument("--expected-repeats", type=int, default=5)
    parser.add_argument("--expected-dataset", action="append")
    args = parser.parse_args()
    analyze(
        args.input_root,
        args.output_dir,
        args.expected_queries,
        args.expected_repeats,
        tuple(args.expected_dataset or DATASETS),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
