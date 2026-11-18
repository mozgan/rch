#!/usr/bin/env python3
"""Run exact page-query correctness checks on pinned multi-source point clouds."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import yaml

UTC = timezone.utc  # noqa: UP017 -- Python 3.10 compatibility

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.application_layouts import (
    APPLICATION_OUTPUT_ROOT, APPLICATION_SCHEMA, APPLICATION_PROTOCOL, NATIVE_LAYOUTS, RULES,
)
from data.synthetic.generators.common import write_xyz_csv
from experiments.runners.run_real_datasets import read_processed_points
from scripts.convert_dataset import load_manifest

DEFAULT_DATASET_IDS = (
    "stanford_bunny",
    "stanford_armadillo",
    "stanford_dragon",
    "usgs_cameron_peak",
    'noaa_santiam_river',
    'noaa_long_island',
    'noaa_southwest_florida',
)
LAYOUTS = (
    ("A0_input", "input", "sample"),
    ("A0_full_scan", "input", "sample"),
    ("A3_isotropic_hilbert", "isotropic_hilbert", "sample"),
    ("A6_rch", "rch", "det_mcd"),
    *((layout, "rch", "det_mcd") for layout in NATIVE_LAYOUTS),
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_environment(order_bin: Path, query_bin: Path) -> dict[str, Any]:
    """Capture host, executable, and source-control identifiers for reproducible runs."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    cache_path = order_bin.resolve().parents[2] / "CMakeCache.txt"
    compiler = None
    if cache_path.is_file():
        for line in cache_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="):
                compiler = line.partition("=")[2]
                break
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "python_version": sys.version,
        "numpy_version": np.__version__,
        "pyyaml_version": yaml.__version__,
        "git_revision": revision,
        "git_worktree_dirty": dirty,
        "cmake_cxx_compiler": compiler,
        "executables": {
            "rch_order_sha256": sha256_file(order_bin),
            "rch_application_query_smoke_sha256": sha256_file(query_bin),
        },
    }


def compress_payload(page_path: Path, compressed_path: Path) -> dict[str, Any]:
    """Compress the page payload (without its 4 KiB container header) with zlib level 6."""
    compressor = zlib.compressobj(level=6, wbits=zlib.MAX_WBITS)
    digest = hashlib.sha256()
    compressed_bytes = 0
    start = perf_counter()
    with page_path.open("rb") as source, compressed_path.open("wb") as destination:
        source.seek(4096)
        while chunk := source.read(1024 * 1024):
            encoded = compressor.compress(chunk)
            if encoded:
                destination.write(encoded)
                digest.update(encoded)
                compressed_bytes += len(encoded)
        tail = compressor.flush(zlib.Z_FINISH)
        destination.write(tail)
        digest.update(tail)
        compressed_bytes += len(tail)
        destination.flush()
    elapsed = perf_counter() - start
    uncompressed_bytes = page_path.stat().st_size - 4096
    return {
        "compressed_file": str(compressed_path.relative_to(ROOT)),
        "compressed_sha256": digest.hexdigest(),
        "compressed_bytes": compressed_bytes,
        "uncompressed_payload_bytes": uncompressed_bytes,
        "compression_ratio": compressed_bytes / uncompressed_bytes
        if uncompressed_bytes
        else 0.0,
        "compression_and_write_seconds": elapsed,
    }


def load_dataset_provenance(
    dataset_id: str,
    raw_dir: Path,
    processed_dir: Path,
    manifest_path: Path = ROOT / "data/manifests/real_datasets.yml",
) -> dict[str, Any]:
    """Fail closed unless raw and converted data match the checked-in manifest."""
    datasets = load_manifest(manifest_path)["datasets"]
    dataset = next((item for item in datasets if item["id"] == dataset_id), None)
    if dataset is None:
        raise ValueError(f"dataset is not present in the pinned manifest: {dataset_id}")

    raw_dir = ROOT / dataset.get("raw_dir", raw_dir)
    processed_dir = ROOT / dataset.get("processed_dir", processed_dir)
    raw_path = raw_dir / str(dataset["filename"])
    processed_path = processed_dir / f"{dataset_id}.ply"
    metadata_path = processed_path.with_suffix(".metadata.json")
    for path in (raw_path, processed_path, metadata_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"required dataset file is missing: {path}; first run scripts/download_dataset.py "
                "and the source converter (make real-data)"
            )

    archive_sha256 = sha256_file(raw_path)
    if archive_sha256 != str(dataset["sha256"]).lower():
        raise ValueError(f"raw archive checksum mismatch: {raw_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    processed_sha256 = sha256_file(processed_path)
    expected_vertices = int(dataset["expected_vertices"])
    if (
        metadata.get("schema") != "rch.processed_dataset.v1"
        or metadata.get("archive_sha256") != archive_sha256
        or metadata.get("processed_sha256") != processed_sha256
        or int(metadata.get("vertex_count", -1)) != expected_vertices
    ):
        raise ValueError(f"processed dataset provenance mismatch: {processed_path}")

    points = read_processed_points(processed_path)
    if len(points) != expected_vertices:
        raise ValueError(
            f"point count mismatch for {dataset_id}: expected {expected_vertices}, got {len(points)}"
        )
    metadata_evidence = []
    for path_field, hash_field in (("metadata_snapshot", "metadata_sha256"), ("index_snapshot", "index_sha256")):
        if dataset.get(path_field):
            path = ROOT / dataset[path_field]
            checksum = sha256_file(path)
            if dataset.get(hash_field) and checksum != dataset[hash_field]:
                raise ValueError("dataset metadata checksum mismatch")
            metadata_evidence.append({"path": str(path.relative_to(ROOT)), "sha256": checksum})
    return {
        "dataset_id": dataset_id,
        "source": dataset.get("source", {}),
        "metadata_evidence": metadata_evidence,
        "acquisition_project": dataset.get("acquisition_project"),
        "sensor_model": dataset.get("sensor_model"),
        "sensor_scope": dataset.get("sensor_scope"),
        "metadata_url": dataset.get("metadata_url"),
        "source_manifest": str(
            Path(dataset.get("manifest_file", manifest_path)).relative_to(ROOT)
        ),
        "source_manifest_sha256": sha256_file(
            Path(dataset.get("manifest_file", manifest_path))
        ),
        "coordinate_conversion": metadata.get("coordinate_conversion"),
        "record_policy": metadata.get("record_policy"),
        "source_format": metadata.get(
            "source_format", metadata.get("source_ply_format")
        ),
        "archive": str(raw_path.relative_to(ROOT)),
        "archive_sha256": archive_sha256,
        "processed_file": str(processed_path.relative_to(ROOT)),
        "processed_sha256": processed_sha256,
        "preprocessing_manifest": str(metadata_path.relative_to(ROOT)),
        "preprocessing_manifest_sha256": sha256_file(metadata_path),
        "source_ply_format": metadata.get("source_ply_format"),
        "point_count": len(points),
        "points": points,
    }


def geometry_descriptors(points: list[Any]) -> dict[str, Any]:
    """Continuous, scale-normalized PCA descriptors; no unvalidated class thresholds."""
    xyz = np.asarray(points, dtype=float)
    extents = np.ptp(xyz, axis=0)
    eigenvalues = np.maximum(np.linalg.eigvalsh(np.cov(xyz, rowvar=False)), 0.0)[::-1]
    largest = float(eigenvalues[0])
    return {
        "scope": "whole dataset, original coordinates; sample covariance, ddof=1",
        "bbox_extents": extents.tolist(),
        "bbox_aspect_ratio": float(max(extents) / min(extents))
        if min(extents) > 0
        else None,
        "covariance_eigenvalues_descending": eigenvalues.tolist(),
        "normalized_eigengaps": (
            (eigenvalues[:-1] - eigenvalues[1:]) / largest
        ).tolist()
        if largest > 0
        else None,
        "linearity": float((eigenvalues[0] - eigenvalues[1]) / largest)
        if largest > 0
        else None,
        "planarity": float((eigenvalues[1] - eigenvalues[2]) / largest)
        if largest > 0
        else None,
        "scattering": float(eigenvalues[2] / largest) if largest > 0 else None,
        "interpretation": "descriptive geometric indicators; not a causal failure map or discrete surface/curve classifier",
    }


def write_identity_order(path: Path, point_count: int) -> None:
    """Write the A0 input-order permutation in rch_order CSV format."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("rank,raw_index,key\n")
        for index in range(point_count):
            handle.write(f"{index},{index},{index}\n")


def write_full_query_matrix(
    path: Path, points: list[Any], seed: int = 2026
) -> dict[str, Any]:
    """Write the frozen 256-window workload, shared by every layout of one dataset."""
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    rng = random.Random(seed)
    sizes = (("small", 0.03125, 86), ("medium", 0.125, 85), ("large", 0.5, 85))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ("query_id", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z")
        )
        for label, fraction, count in sizes:
            for index in range(count):
                lows: list[float] = []
                highs: list[float] = []
                for axis in range(3):
                    extent = maximum[axis] - minimum[axis]
                    width = extent * fraction
                    center = rng.uniform(
                        minimum[axis] + width / 2, maximum[axis] - width / 2
                    )
                    lows.append(center - width / 2)
                    highs.append(center + width / 2)
                writer.writerow(
                    (
                        f"{label}_{index:03d}",
                        *[format(v, ".17g") for v in (*lows, *highs)],
                    )
                )
    return {
        "seed": seed,
        "count": 256,
        "size_groups": {name: count for name, _, count in sizes},
        "file_sha256": sha256_file(path),
    }


def run_ordering(
    order_bin: Path,
    dataset_id: str,
    layout_id: str,
    method: str,
    frame_estimator: str,
    points_path: Path,
    point_count: int,
    output_dir: Path,
    timing_repeats: int = 5,
) -> tuple[Path, Path]:
    """Generate one ordering with its versioned allocator and refinement off."""
    order_path = output_dir / f"{dataset_id}__{layout_id}.order.csv"
    manifest_path = output_dir / f"{dataset_id}__{layout_id}.manifest.json"
    if layout_id.startswith("A0_"):
        return order_path, manifest_path

    subprocess.run(
        [
            str(order_bin),
            "--input",
            str(points_path),
            "--method",
            method,
            "--frame-estimator",
            frame_estimator,
            "--bit-allocator",
            RULES[layout_id]["bit_allocator"],
            "--uniform-bits",
            "10",
            "--min-axis-bits",
            "1",
            "--refinement",
            "off",
            "--timing-repeats",
            str(timing_repeats),
            "--output",
            str(order_path),
            "--manifest",
            str(manifest_path),
        ],
        check=True,
        cwd=ROOT,
    )
    result = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        result.get("status") != "ok"
        or int(result.get("point_count", -1)) != point_count
        or result.get("refinement") != "off"
        or int(result.get("uniform_bits", -1)) != 10
        or result.get("bit_allocator") != RULES[layout_id]["bit_allocator"]
        or result.get("method") != method
        or (method == "rch" and result.get("frame_estimator") != "det_mcd")
        or result.get("controlled_frame_quantizer", False)
    ):
        raise ValueError(
            f"ordering manifest failed smoke configuration check: {manifest_path}"
        )
    return order_path, manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/manifests/real_datasets.yml"
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=ROOT / "data/raw/stanford_3d_scanning"
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=ROOT / "data/processed/stanford_3d_scanning",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / Path(APPLICATION_OUTPUT_ROOT).parent / "correctness_smoke",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        help="dataset to include; repeat the option for multiple datasets (default: three Stanford meshes and four LiDAR sites)",
    )
    parser.add_argument(
        "--measure-warm-cache-compression",
        action="store_true",
        help="run one warm-up plus repeated warm-cache queries and zlib level-6 size checks",
    )
    parser.add_argument(
        "--full-query-matrix",
        action="store_true",
        help="use the frozen seeded 256-query workload instead of four smoke queries",
    )
    parser.add_argument("--measured-repeats", type=int, default=5)
    parser.add_argument("--ordering-repeats", type=int, default=5)
    parser.add_argument(
        "--rch-order-bin", type=Path, default=ROOT / "build/bench/src/cli/rch_order"
    )
    parser.add_argument(
        "--smoke-bin",
        type=Path,
        default=ROOT / "build/bench/src/cli/rch_application_query_smoke",
    )
    return parser.parse_args()


def main() -> int:
    workflow_start = perf_counter()
    args = parse_args()
    if not 1 <= args.ordering_repeats <= 10000:
        raise ValueError("ordering repeats must be between 1 and 10000")
    protocol_path = ROOT / "experiments/runlists/real/application_window_query.yaml"
    protocol = yaml.safe_load(protocol_path.read_text())
    if (
        protocol.get("schema") != "rch.application_query_protocol"
        or protocol.get("protocol_id") != APPLICATION_PROTOCOL
    ):
        raise ValueError("expected shared native-rule application protocol")
    workload = protocol["query_workload"]
    if (
        workload["seed"] != 2026
        or workload["count_per_dataset"] != 256
        or workload["size_fractions_of_each_bbox_extent"]
        != [
            {"fraction": f, "query_count": n}
            for f, n in ((0.03125, 86), (0.125, 85), (0.5, 85))
        ]
    ):
        raise ValueError(
            "query protocol changed; update and validate workload implementation"
        )
    if (
        protocol["layouts"]["bit_rule"]["uniform_bits_per_axis"] != 10
        or protocol["compression"]["level"] != 6
    ):
        raise ValueError("layout/codec protocol mismatch")
    if args.full_query_matrix and (
        args.measured_repeats < 5 or args.ordering_repeats < 5
    ):
        raise ValueError(
            "full matrix requires at least five query and ordering repeats"
        )
    if (
        protocol["layouts"].get("rule_by_layout") != RULES
        or protocol["layouts"]["ids"] != [layout[0] for layout in LAYOUTS]
        or protocol["record_and_pages"]["record_bytes"] != 32
        or protocol["record_and_pages"]["page_bytes"] != 4096
    ):
        raise ValueError("storage/layout protocol mismatch")
    selected_dataset_ids = tuple(args.dataset or DEFAULT_DATASET_IDS)
    if len(selected_dataset_ids) != len(set(selected_dataset_ids)):
        raise ValueError("--dataset may not be repeated with the same ID")
    if args.measured_repeats < 1 or args.measured_repeats > 10_000:
        raise ValueError("--measured-repeats must be between 1 and 10000")
    output_dir = args.output_dir.resolve()
    try:
        output_dir.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(
            "smoke output must remain under the repository root"
        ) from error
    if output_dir.exists():
        raise FileExistsError(
            f"output directory already exists; choose a new --output-dir: {output_dir}"
        )
    if not args.rch_order_bin.is_file() or not args.smoke_bin.is_file():
        raise FileNotFoundError(
            "required executables are missing; configure with RCH_BUILD_TOOLS=ON and build "
            "targets rch_order and rch_application_query_smoke"
        )

    provenance_records = [
        load_dataset_provenance(
            dataset_id,
            args.raw_dir if args.raw_dir.is_absolute() else ROOT / args.raw_dir,
            args.processed_dir
            if args.processed_dir.is_absolute()
            else ROOT / args.processed_dir,
            args.manifest.resolve(),
        )
        for dataset_id in selected_dataset_ids
    ]
    output_dir.mkdir(parents=True)
    input_dir = output_dir / "inputs"
    order_dir = output_dir / "orders"
    result_dir = output_dir / "results"
    for directory in (input_dir, order_dir, result_dir):
        directory.mkdir()

    run_manifest: dict[str, Any] = {
        "schema": APPLICATION_SCHEMA,
        "protocol": protocol["protocol_id"],
        "created_utc": datetime.now(UTC).isoformat(),
        "ordering": {
            "layouts": [layout[0] for layout in LAYOUTS],
            "bit_rule": "C0 arms plus distinct native C2/C3/C4 RCH layouts",
            "layout_rules": RULES,
            "query_layout_order": "one seeded permutation per dataset; not interleaved across repeats",
            "refinement": "off",
        },
        "query_count_per_dataset_layout": 256 if args.full_query_matrix else 4,
        "query_workload": {
            "mode": "seeded_bbox_cubes"
            if args.full_query_matrix
            else "four_query_smoke",
            "seed": 2026 if args.full_query_matrix else None,
            "size_fractions_and_counts": [[0.03125, 86], [0.125, 85], [0.5, 85]]
            if args.full_query_matrix
            else None,
        },
        "environment": capture_environment(args.rch_order_bin, args.smoke_bin),
        "cache_protocol": (
            {
                "mode": "warm_cache_only",
                "warmup_workload_passes_per_layout": 1,
                "measured_workload_repeats": args.measured_repeats,
                "global_cache_drop": False,
                "process_io_counter": "Linux /proc/self/io read_bytes when available",
            }
            if args.measure_warm_cache_compression or args.full_query_matrix
            else None
        ),
        "compression_protocol": (
            {
                "codec": "zlib wrapper with DEFLATE payload",
                "level": 6,
                "scope": "page payload excluding 4096-byte page-file header",
                "compressed_query_measured": False,
                "zlib_compile_version": zlib.ZLIB_VERSION,
                "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
            }
            if args.measure_warm_cache_compression or args.full_query_matrix
            else None
        ),
        "expected_dataset_ids": list(selected_dataset_ids),
        "ordering_repeats": args.ordering_repeats,
        "protocol_sha256": sha256_file(protocol_path),
        "protocol_definition": protocol,
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in [
                Path(__file__),
                ROOT / "experiments/application_layouts.py",
                ROOT / "analysis/scripts/analyze_application_query_metrics.py",
                ROOT / "analysis/scripts/make_application_artifacts.py",
                *sorted((ROOT / "src").rglob("*.cpp")),
                *sorted((ROOT / "include").rglob("*.hpp")),
            ]
        },
        "datasets": [],
    }

    for provenance in provenance_records:
        dataset_start = perf_counter()
        dataset_id = str(provenance["dataset_id"])
        points = provenance.pop("points")
        provenance["geometry"] = geometry_descriptors(points)
        points_path = input_dir / f"{dataset_id}.csv"
        write_xyz_csv(points_path, points)
        dataset_orders: dict[str, tuple[Path, Path]] = {}
        ordering_wall_seconds: dict[str, float] = {}
        for layout_id, method, frame in LAYOUTS:
            ordering_start = perf_counter()
            dataset_orders[layout_id] = run_ordering(
                args.rch_order_bin,
                dataset_id,
                layout_id,
                method,
                frame,
                points_path,
                len(points),
                order_dir,
                args.ordering_repeats,
            )
            if layout_id.startswith("A0_"):
                write_identity_order(dataset_orders[layout_id][0], len(points))
                dataset_orders[layout_id][1].write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "layout_id": layout_id,
                            "point_count": len(points),
                            "refinement": "off",
                            "uniform_bits": 10,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            ordering_wall_seconds[layout_id] = perf_counter() - ordering_start

        dataset_result_dir = result_dir / dataset_id
        dataset_result_dir.mkdir()
        query_file = input_dir / f"{dataset_id}.queries.csv"
        query_metadata = (
            write_full_query_matrix(query_file, points)
            if args.full_query_matrix
            else None
        )
        if query_metadata is not None:
            query_file.with_suffix(".metadata.json").write_text(
                json.dumps(query_metadata, indent=2) + "\n"
            )
        a0_order, _ = dataset_orders["A0_input"]
        a3_order, _ = dataset_orders["A3_isotropic_hilbert"]
        a6_order, _ = dataset_orders["A6_rch"]
        layout_schedule = [layout[0] for layout in LAYOUTS]
        random.Random(2026 + len(run_manifest["datasets"])).shuffle(layout_schedule)
        provenance["layout_schedule"] = layout_schedule
        subprocess.run(
            [
                str(args.smoke_bin),
                "--dataset-id",
                dataset_id,
                "--points",
                str(points_path),
                "--a0-order",
                str(a0_order),
                "--a3-order",
                str(a3_order),
                "--a6-order",
                str(a6_order),
                *[
                    value
                    for number, layout in zip((2, 3, 4), NATIVE_LAYOUTS)
                    for value in (
                        f"--a6-c{number}-order",
                        str(dataset_orders[layout][0]),
                    )
                ],
                "--layout-order",
                ",".join(layout_schedule),
                "--source-sha256",
                provenance["processed_sha256"],
                "--output-dir",
                str(dataset_result_dir),
                *(
                    ["--query-windows", str(query_file)]
                    if args.full_query_matrix
                    else []
                ),
                *(
                    ["--warm-cache-repeats", str(args.measured_repeats)]
                    if args.measure_warm_cache_compression or args.full_query_matrix
                    else []
                ),
            ],
            check=True,
            cwd=ROOT,
        )

        provenance["input_csv"] = str(points_path.relative_to(ROOT))
        provenance["input_csv_sha256"] = sha256_file(points_path)
        provenance["ordering_wall_seconds"] = ordering_wall_seconds
        provenance["order_files"] = {
            layout_id: {
                "path": str(paths[0].relative_to(ROOT)),
                "sha256": sha256_file(paths[0]),
                "manifest_path": str(paths[1].relative_to(ROOT)),
                "manifest_sha256": sha256_file(paths[1]),
            }
            for layout_id, paths in dataset_orders.items()
        }
        provenance["query_results"] = {
            name: {
                "path": str((dataset_result_dir / name).relative_to(ROOT)),
                "sha256": sha256_file(dataset_result_dir / name),
            }
            for name in ("query_windows.csv", "query_results.csv")
        }
        if query_metadata is not None:
            provenance["query_workload"] = {
                **query_metadata,
                "file": str(query_file.relative_to(ROOT)),
            }
        if args.measure_warm_cache_compression or args.full_query_matrix:
            metrics_path = dataset_result_dir / "query_metrics.csv"
            with metrics_path.open("r", encoding="utf-8", newline="") as metrics_file:
                metrics_rows = list(csv.DictReader(metrics_file))
            query_count = 256 if args.full_query_matrix else 4
            expected_metrics = len(LAYOUTS) * query_count * args.measured_repeats
            if len(metrics_rows) != expected_metrics or any(
                row["oracle_match"] != "true" for row in metrics_rows
            ):
                raise ValueError(
                    f"warm-cache query metrics failed validation: {metrics_path}"
                )
            available_io_rows = sum(
                bool(row["process_read_bytes_delta"]) for row in metrics_rows
            )
            provenance["warm_cache_query_metrics"] = {
                "path": str(metrics_path.relative_to(ROOT)),
                "sha256": sha256_file(metrics_path),
                "row_count": len(metrics_rows),
                "all_queries_match_oracle": True,
                "process_read_bytes_counter_rows": available_io_rows,
                "process_read_bytes_counter_status": (
                    "available"
                    if available_io_rows == len(metrics_rows)
                    else "unavailable"
                    if available_io_rows == 0
                    else "partially_available"
                ),
                "logical_bytes_are_page_count_times_4096": True,
            }

            compressed: dict[str, Any] = {}
            for layout_id, _, _ in LAYOUTS:
                page_path = dataset_result_dir / f"{layout_id}.page"
                compressed_path = dataset_result_dir / f"{layout_id}.payload.zlib"
                compressed[layout_id] = compress_payload(page_path, compressed_path)
            provenance["compression"] = compressed
        integrity_records: dict[str, Any] = {}
        for layout_id, _, _ in LAYOUTS:
            integrity_path = dataset_result_dir / f"{layout_id}.integrity.json"
            integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
            page_path = dataset_result_dir / f"{layout_id}.page"
            index_path = dataset_result_dir / f"{layout_id}.index"
            integrity_records[layout_id] = {
                "manifest": str(integrity_path.relative_to(ROOT)),
                "manifest_sha256": sha256_file(integrity_path),
                "page_file": str(page_path.relative_to(ROOT)),
                "page_file_sha256": sha256_file(page_path),
                "page_file_bytes": page_path.stat().st_size,
                "index_file": str(index_path.relative_to(ROOT)),
                "index_file_sha256": sha256_file(index_path),
                "index_file_bytes": index_path.stat().st_size,
                "page_count": integrity["page_count"],
                "peak_rss_kib": integrity.get("peak_rss_kib"),
                "rss_scope": "process cumulative through storage validation; not layout-exclusive",
                "query_memory": json.loads(
                    (dataset_result_dir / f"{layout_id}.query_memory.json").read_text()
                ),
                "query_memory_file": str(
                    (dataset_result_dir / f"{layout_id}.query_memory.json").relative_to(
                        ROOT
                    )
                ),
                "query_memory_sha256": sha256_file(
                    dataset_result_dir / f"{layout_id}.query_memory.json"
                ),
                "payload_checksum_verified": integrity[
                    "page_payload_checksum_verified"
                ],
                "directory_checksum_verified": integrity[
                    "page_directory_checksum_verified"
                ],
                "readback_verified": integrity["page_readback_verified"],
                "aabb_coverage_verified": integrity["page_aabb_coverage_verified"],
                "flush_called": integrity["flush_called"],
                "fsync_performed": integrity["fsync_performed"],
                "page_file_write_seconds": integrity["page_file_write_seconds"],
                "index_build_seconds": integrity["index_build_seconds"],
                "index_write_seconds": integrity["index_write_seconds"],
                "page_checksum_verify_seconds": integrity[
                    "page_checksum_verify_seconds"
                ],
                "page_readback_verify_seconds": integrity[
                    "page_readback_verify_seconds"
                ],
            }
        provenance["storage_integrity"] = integrity_records
        provenance["ordering_diagnostics"] = {
            layout: json.loads(paths[1].read_text())
            for layout, paths in dataset_orders.items()
        }
        provenance["amortizable_preparation_seconds"] = {
            layout: float(
                provenance["ordering_diagnostics"][layout].get("sort_seconds", 0.0)
            )
            + values["page_file_write_seconds"]
            + values["index_build_seconds"]
            + values["index_write_seconds"]
            for layout, values in integrity_records.items()
        }
        provenance["preparation_seconds"] = {
            "ordering_wall_seconds": ordering_wall_seconds,
            "page_file_write_seconds": {
                layout: values["page_file_write_seconds"]
                for layout, values in integrity_records.items()
            },
            "index_build_seconds": {
                layout: values["index_build_seconds"]
                for layout, values in integrity_records.items()
            },
            "index_write_seconds": {
                layout: values["index_write_seconds"]
                for layout, values in integrity_records.items()
            },
            "total_by_layout": {
                layout: ordering_wall_seconds[layout]
                + values["page_file_write_seconds"]
                + values["index_build_seconds"]
                + values["index_write_seconds"]
                for layout, values in integrity_records.items()
            },
        }
        provenance["dataset_elapsed_seconds"] = perf_counter() - dataset_start
        provenance["preparation_seconds"]["scope"] = (
            "sum of ordering subprocess wall time (includes repeated ordering), page write, index build/write; excludes dataset parse and validation"
        )
        run_manifest["datasets"].append(provenance)

    for binary, field in (
        (args.rch_order_bin, "rch_order_sha256"),
        (args.smoke_bin, "rch_application_query_smoke_sha256"),
    ):
        if sha256_file(binary) != run_manifest["environment"]["executables"][field]:
            raise ValueError("application executable changed during experiment")
    if sha256_file(protocol_path) != run_manifest["protocol_sha256"]:
        raise ValueError("application protocol changed during experiment")
    for relative, checksum in run_manifest["source_sha256"].items():
        if sha256_file(ROOT / relative) != checksum:
            raise ValueError("application source changed during experiment")
    run_manifest["workflow_elapsed_seconds"] = perf_counter() - workflow_start
    run_manifest["elapsed_scope"] = (
        "host wall time including provenance validation, CSV conversion, repeated ordering, storage validation, oracle, queries and compression; excludes download and final manifest write"
    )
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Correctness smoke passed. Manifest: {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
