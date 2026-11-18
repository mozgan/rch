#!/usr/bin/env python3
"""Convert pinned USGS/NOAA LAZ or COPC tiles, preserving every point in metres."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import sys
from pathlib import Path

import laspy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.convert_dataset import bounds, load_manifest, sha256_file, write_ascii_ply
from scripts.download_dataset import ensure_dataset


def convert_laz(dataset: dict, raw: Path, processed: Path) -> Path:
    """Check source hash/count/CRS/units; keep source order, returns and classes."""
    for path_field, hash_field in (("metadata_snapshot", "metadata_sha256"), ("index_snapshot", "index_sha256")):
        if hash_field in dataset and sha256_file(ROOT / dataset[path_field]) != dataset[hash_field]:
            raise ValueError("source metadata checksum mismatch")
    source = raw / dataset["filename"]
    if sha256_file(source) != dataset["sha256"]:
        raise ValueError("USGS source checksum mismatch")
    if source.stat().st_size != dataset["expected_bytes"]:
        raise ValueError("USGS source byte count mismatch")
    output = processed / f"{dataset['id']}.ply"
    metadata_path = output.with_suffix(".metadata.json")
    converter_hash = sha256_file(Path(__file__))
    if output.exists() and metadata_path.exists():
        old = json.loads(metadata_path.read_text())
        if (
            old.get("archive_sha256") == dataset["sha256"]
            and old.get("converter_sha256") == converter_hash
            and old.get("vertex_count") == dataset["expected_vertices"]
            and old.get("processed_sha256") == sha256_file(output)
            and old.get("conversion_specification") == dataset
        ):
            return output
    with laspy.open(source) as reader:
        header = reader.header
        if header.point_count != dataset["expected_vertices"]:
            raise ValueError("USGS source point count mismatch")
        crs = header.parse_crs()
        if crs is None or not crs.is_compound:
            raise ValueError(
                "USGS source must declare a compound projected/vertical CRS"
            )
        horizontal, vertical = crs.sub_crs_list
        if (
            horizontal.to_epsg() != dataset["horizontal_epsg"]
            or vertical.to_epsg() != dataset["vertical_epsg"]
        ):
            raise ValueError("USGS source CRS mismatch")
        factors = [axis.unit_conversion_factor for axis in crs.axis_info]
        factor = float(dataset["coordinate_scale_to_metre"])
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("invalid declared coordinate conversion factor")
        if (
            len(factors) != 3
            or any(not math.isclose(f, factor, rel_tol=1e-12) for f in factors)
            or not math.isclose(
                dataset["coordinate_scale_to_metre"], factor, rel_tol=1e-12
            )
        ):
            raise ValueError("USGS source axis units mismatch")
        points = []
        for chunk in reader.chunk_iterator(100_000):
            # laspy scaled access applies the LAS integer scale and offset first.
            points.extend(zip(chunk.x * factor, chunk.y * factor, chunk.z * factor))
        if len(points) != header.point_count:
            raise ValueError("USGS decoded point count mismatch")
        source_crs_wkt = crs.to_wkt()
        source_scales, source_offsets = header.scales.tolist(), header.offsets.tolist()
    if any(not all(math.isfinite(v) for v in point) for point in points):
        raise ValueError("USGS contains non-finite coordinates")
    write_ascii_ply(output, points)
    lo, hi = bounds(points)
    metadata = {
        "schema": "rch.processed_dataset.v1",
        "dataset_id": dataset["id"],
        "label": dataset["label"],
        "source_format": "LAZ",
        "source_filename": dataset["filename"],
        "archive_sha256": dataset["sha256"],
        "processed_sha256": sha256_file(output),
        "vertex_count": len(points),
        "bbox_min": list(lo),
        "bbox_max": list(hi),
        "source_crs_wkt": source_crs_wkt,
        "source_las_scales": source_scales,
        "source_las_offsets": source_offsets,
        "coordinate_conversion": {
            "xyz_factor": factor,
            "output_units": "metre",
            "translation": [0, 0, 0],
            "reprojection": False,
        },
        "record_policy": "all records, original order; no crop, thinning, filtering or deduplication",
        "converter_sha256": converter_hash,
        "conversion_specification": dataset,
        "software_versions": {
            p: importlib.metadata.version(p)
            for p in ("laspy", "lazrs", "pyproj", "numpy")
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "data/manifests/usgs_3dep.yml"
    )
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/usgs_3dep")
    parser.add_argument(
        "--processed-dir", type=Path, default=ROOT / "data/processed/usgs_3dep"
    )
    args = parser.parse_args()
    for dataset in load_manifest(args.manifest)["datasets"]:
        ensure_dataset(dataset, args.raw_dir)
        print(convert_laz(dataset, args.raw_dir, args.processed_dir))


if __name__ == "__main__":
    main()
