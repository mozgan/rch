#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# create_demo_dataset.py — deterministic demo fixture and runlist builder.
#
# References:
#   - George E. P. Box, Mervin E. Muller, A Note on the Generation of Random
#     Normal Deviates, 1958, DOI: 10.1214/aoms/1177706645.
#   - National Institute of Standards and Technology, Secure Hash Standard,
#     2015, DOI: 10.6028/NIST.FIPS.180-4.
# ----------------------------------------------------------------------------
"""Create deterministic demo data and canonical benchmark runlists for checks.

Algorithm: generate two fixed Gaussian ellipsoid clouds, write point-only PLY,
package each with deterministic gzip/tar metadata, then emit checksum-pinned
demo manifests and reduced runlists.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import tarfile
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNLIST_ROOT = REPO_ROOT / "experiments" / "runlists"
SYNTHETIC_RUNLIST_SOURCES = {
    "table_3_locality": RUNLIST_ROOT / "table_3_locality.yaml",
    "table_4_outlier": RUNLIST_ROOT / "table_4_outlier.yaml",
    "table_5_runtime": RUNLIST_ROOT / "table_5_runtime.yaml",
}
REAL_RUNLIST_SOURCE = RUNLIST_ROOT / "table_2_dataset_summary.yaml"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.synthetic.generators.gaussian_ellipsoid import ellipsoid_points  # noqa: E402

POINT_COUNT = 128
SEED = 0
DEMO_TIMING_REPEATS = 3
DEMO_REAL_DATASETS = [
    {
        "id": "rch_demo_bunny",
        "label": "RCH demo Bunny-scale cloud",
        "geometry_id": "E3",
        "axes": (1.0, 0.75, 0.55),
        "source_notes": "Deterministic E3 demo cloud; not the Stanford Bunny dataset.",
    },
    {
        "id": "rch_demo_armadillo",
        "label": "RCH demo Armadillo-scale cloud",
        "geometry_id": "E4",
        "axes": (1.8, 0.8, 0.6),
        "source_notes": "Deterministic E4 demo cloud; not the Stanford Armadillo dataset.",
    },
]


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML mapping used as source runlist/catalog template."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping YAML at {path}")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_ply(points: list[tuple[float, float, float]]) -> bytes:
    """Return point-only ASCII PLY bytes for demo fixture archives."""
    for point in points:
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise ValueError("demo PLY points must be finite 3D coordinates")
    lines = [
        "ply",
        "format ascii 1.0",
        "comment generated_by scripts/create_demo_dataset.py",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    lines.extend(f"{x:.9g} {y:.9g} {z:.9g}" for x, y, z in points)
    return ("\n".join(lines) + "\n").encode("ascii")


def write_reproducible_tar_gz(path: Path, inner_path: str, payload: bytes) -> None:
    """Write gzip-compressed tar with fixed metadata for byte reproducibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            info = tarfile.TarInfo(inner_path)
            info.size = len(payload)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))
    path.write_bytes(buffer.getvalue())


def all_algorithm_ids() -> list[str]:
    """Return the canonical demo algorithm list from table_3_locality."""
    runlist = load_yaml(SYNTHETIC_RUNLIST_SOURCES["table_3_locality"])
    return [str(item) for item in runlist["algorithm_ids"]]


def all_bit_rules() -> list[dict[str, object]]:
    """Return the canonical demo bit-rule list from table_3_locality."""
    runlist = load_yaml(SYNTHETIC_RUNLIST_SOURCES["table_3_locality"])
    return [dict(item) for item in runlist["bit_rules"]]


def repo_relative(path: Path) -> str:
    """Render repo-local paths relatively; keep external temp paths absolute."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def write_synthetic_runlist(path: Path, name: str) -> None:
    source = SYNTHETIC_RUNLIST_SOURCES.get(name)
    if source is None:
        raise ValueError(f"unknown synthetic runlist: {name}")
    payload = deepcopy(load_yaml(source))
    if "timing_repeats" in payload:
        payload["timing_repeats"] = DEMO_TIMING_REPEATS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def write_real_runlist(path: Path, manifest: Path, processed_dir: Path) -> None:
    payload = deepcopy(load_yaml(REAL_RUNLIST_SOURCE))
    payload["dataset_manifest"] = repo_relative(manifest)
    payload["processed_dir"] = repo_relative(processed_dir)
    payload["dataset_ids"] = [str(item["id"]) for item in DEMO_REAL_DATASETS]
    payload["geometry_ids"] = {
        str(item["id"]): str(item["geometry_id"]) for item in DEMO_REAL_DATASETS
    }
    payload["contamination_ids"] = ["D0"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def write_real_catalog(path: Path) -> None:
    payload = {
        "schema": "rch.real_dataset_catalog.v1",
        "datasets": [
            {
                "id": item["id"],
                "family": "RCH demo",
                "status": "measured",
                "source_url": repo_relative(
                    REPO_ROOT / "data" / "manifests" / "rch_demo.yml"
                ),
            }
            for item in DEMO_REAL_DATASETS
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def create_demo_dataset(args: argparse.Namespace) -> dict[str, str]:
    """Create all demo source archives, manifests, runlists, and A7 fixture."""
    dataset_entries: list[dict[str, object]] = []
    for index, item in enumerate(DEMO_REAL_DATASETS):
        dataset_id = str(item["id"])
        points = ellipsoid_points(POINT_COUNT, tuple(item["axes"]), SEED + index)
        ply_bytes = write_ply(points)
        archive = args.source_dir / f"{dataset_id}.tar.gz"
        write_reproducible_tar_gz(archive, f"{dataset_id}.ply", ply_bytes)
        dataset_entries.append(
            {
                "id": dataset_id,
                "label": item["label"],
                "url": repo_relative(archive),
                "filename": archive.name,
                "sha256": sha256_file(archive),
                "archive_type": "tar.gz",
                "inner_path": f"{dataset_id}.ply",
                "expected_vertices": POINT_COUNT,
                "source_notes": item["source_notes"],
            }
        )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "schema": "rch.dataset_manifest.v1",
        "datasets": dataset_entries,
    }
    args.manifest.write_text(
        yaml.safe_dump(manifest_payload, sort_keys=False), encoding="utf-8"
    )
    write_real_catalog(args.real_catalog)

    write_synthetic_runlist(
        args.synthetic_locality_runlist,
        "table_3_locality",
    )
    write_synthetic_runlist(
        args.synthetic_outlier_runlist,
        "table_4_outlier",
    )
    write_synthetic_runlist(
        args.synthetic_runtime_runlist,
        "table_5_runtime",
    )
    write_real_runlist(args.real_runlist, args.manifest, args.processed_dir)

    args.a7_output_dir.mkdir(parents=True, exist_ok=True)
    (args.a7_output_dir / "a7_cgal_spatial_sort.csv").write_text(
        "\n".join(
            [
                "algorithm_id,policy,point_count,order_path,permutation_hash,permutation",
                "A7_cgal_spatial_sort,demo,64,,demo,0 1 2 3 4 5 6 7",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (args.a7_output_dir / "a7_cgal_spatial_sort.manifest.json").write_text(
        json.dumps(
            {
                "schema": "rch.demo_a7.v1",
                "source": "scripts/create_demo_dataset.py",
                "point_count": POINT_COUNT,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": str(args.manifest),
        "real_catalog": str(args.real_catalog),
        "synthetic_locality_runlist": str(args.synthetic_locality_runlist),
        "synthetic_outlier_runlist": str(args.synthetic_outlier_runlist),
        "synthetic_runtime_runlist": str(args.synthetic_runtime_runlist),
        "real_runlist": str(args.real_runlist),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--real-catalog", type=Path, required=True)
    parser.add_argument("--synthetic-locality-runlist", type=Path, required=True)
    parser.add_argument("--synthetic-outlier-runlist", type=Path, required=True)
    parser.add_argument("--synthetic-runtime-runlist", type=Path, required=True)
    parser.add_argument("--real-runlist", type=Path, required=True)
    parser.add_argument("--a7-output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(create_demo_dataset(parse_args()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
