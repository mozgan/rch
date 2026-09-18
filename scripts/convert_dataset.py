#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# convert_dataset.py — Real dataset canonical PLY converter
#
# References:
#   - Greg Turk, The PLY Polygon File Format, 1994.
#   - Library of Congress, Polygon File Format (PLY) Family, 2025.
#   - National Institute of Standards and Technology, Secure Hash Standard,
#     2015, DOI: 10.6028/NIST.FIPS.180-4.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Convert Stanford PLY archives into processed point-only ASCII PLY.

Algorithm:
  1. Extract the manifest-selected PLY member from `.tar.gz` or `.gz`.
  2. Parse the PLY header and locate scalar vertex properties `x`, `y`, `z`.
  3. Read ASCII or binary-endian vertices, rejecting non-finite coordinates.
  4. Emit a point-only ASCII PLY plus SHA-256/bounds sidecar metadata.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import struct
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
Point = tuple[float, float, float]

SCALAR_TYPES: dict[str, tuple[str, int]] = {
    "char": ("b", 1),
    "uchar": ("B", 1),
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "short": ("h", 2),
    "ushort": ("H", 2),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int": ("i", 4),
    "uint": ("I", 4),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "float64": ("d", 8),
}


@dataclass(frozen=True)
class PlyHeader:
    """Parsed PLY header fields needed for point-cloud conversion."""

    fmt: str
    vertex_count: int
    vertex_properties: list[tuple[str, str]]
    header_bytes: int


def sha256_bytes(data: bytes) -> str:
    """Return SHA-256 for in-memory bytes used in metadata provenance."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return SHA-256 for a processed file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    """Load Real YAML manifest and require a dataset list."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("datasets"), list):
        raise ValueError(f"invalid dataset manifest: {path}")
    return data


def manifest_path_component(value: object, field_name: str) -> str:
    """Return a manifest string that is safe as one portable path component."""
    if not isinstance(value, str):
        raise ValueError(f"manifest {field_name} must be a string: {value}")
    path = Path(value)
    if (
        path.is_absolute()
        or value in {"", ".", ".."}
        or "/" in value
        or "\\" in value
        or len(path.parts) != 1
    ):
        raise ValueError(
            f"manifest {field_name} must be a plain path component: {value}"
        )
    return value


def parse_ply_header(data: bytes) -> PlyHeader:
    """Parse PLY header and retain vertex scalar properties.

    PLY headers are ASCII lines. The parser accepts LF and CRLF line endings,
    then records the byte offset immediately after `end_header`.
    """
    header_bytes = 0
    for raw_line in data.splitlines(keepends=True):
        header_bytes += len(raw_line)
        if raw_line.strip() == b"end_header":
            break
    else:
        raise ValueError("PLY end_header not found")
    text = data[:header_bytes].decode("ascii", errors="strict")
    lines = text.splitlines()
    if not lines or lines[0] != "ply":
        raise ValueError("not a PLY file")
    fmt = ""
    vertex_count = 0
    vertex_properties: list[tuple[str, str]] = []
    in_vertex = False
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        if (
            parts[0] == "format"
            and len(parts) == 3
            and parts[2] == "1.0"
            and parts[1] == "ascii"
        ):
            fmt = parts[1]
        elif (
            parts[0] == "format"
            and len(parts) == 3
            and parts[2] == "1.0"
            and parts[1] in {
                "binary_big_endian",
                "binary_little_endian",
            }
        ):
            fmt = parts[1]
        elif len(parts) == 3 and parts[:2] == ["element", "vertex"]:
            vertex_count = int(parts[2])
            if vertex_count < 0:
                raise ValueError("PLY vertex count must be non-negative")
            in_vertex = True
        elif parts[0] == "element":
            in_vertex = False
        elif in_vertex and parts[0] == "property":
            if len(parts) < 3:
                raise ValueError(f"malformed vertex property line: {line}")
            if parts[1] == "list":
                raise ValueError("list vertex properties are unsupported")
            if len(parts) != 3:
                raise ValueError(f"malformed vertex property line: {line}")
            if parts[1] not in SCALAR_TYPES:
                raise ValueError(f"unsupported PLY scalar type: {parts[1]}")
            vertex_properties.append((parts[2], parts[1]))
    if fmt not in {"ascii", "binary_big_endian", "binary_little_endian"}:
        raise ValueError(f"unsupported PLY format: {fmt}")
    names = [name for name, _ in vertex_properties]
    if not {"x", "y", "z"}.issubset(names):
        raise ValueError("PLY vertex element must contain x/y/z")
    return PlyHeader(fmt, vertex_count, vertex_properties, header_bytes)


def read_ascii_vertices(stream: io.BytesIO, header: PlyHeader) -> list[Point]:
    """Read ASCII vertex lines and keep only finite \(x,y,z\) coordinates."""
    points: list[Point] = []
    property_names = [name for name, _ in header.vertex_properties]
    x_i, y_i, z_i = (property_names.index(axis) for axis in ("x", "y", "z"))
    text = io.TextIOWrapper(stream, encoding="ascii", newline="\n")
    for _ in range(header.vertex_count):
        line = text.readline()
        if not line:
            raise ValueError("ASCII PLY ended before all vertices were read")
        values = line.split()
        if len(values) < len(header.vertex_properties):
            raise ValueError("ASCII PLY vertex row has too few properties")
        point = (float(values[x_i]), float(values[y_i]), float(values[z_i]))
        if not all(math.isfinite(value) for value in point):
            raise ValueError("non-finite PLY coordinate")
        points.append(point)
    return points


def read_scalar(handle: BinaryIO, endian: str, scalar_type: str) -> float | int:
    """Read one binary PLY scalar using the header-declared type."""
    if scalar_type not in SCALAR_TYPES:
        raise ValueError(f"unsupported PLY scalar type: {scalar_type}")
    code, size = SCALAR_TYPES[scalar_type]
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("binary PLY ended before all vertices were read")
    return struct.unpack(endian + code, data)[0]


def read_binary_vertices(
    stream: io.BytesIO, header: PlyHeader, endian: str
) -> list[Point]:
    """Read binary PLY vertices and retain \(x,y,z\) only."""
    points: list[Point] = []
    property_names = [name for name, _ in header.vertex_properties]
    for _ in range(header.vertex_count):
        values: dict[str, float | int] = {}
        for name, scalar_type in header.vertex_properties:
            values[name] = read_scalar(stream, endian, scalar_type)
        point = (float(values["x"]), float(values["y"]), float(values["z"]))
        if not all(math.isfinite(value) for value in point):
            raise ValueError("non-finite PLY coordinate")
        points.append(point)
    return points


def read_ply_points(data: bytes) -> tuple[list[Point], PlyHeader]:
    """Read supported PLY bytes into deterministic Point tuples."""
    header = parse_ply_header(data)
    stream = io.BytesIO(data[header.header_bytes :])
    if header.fmt == "ascii":
        return read_ascii_vertices(stream, header), header
    endian = ">" if header.fmt == "binary_big_endian" else "<"
    return read_binary_vertices(stream, header, endian), header


def archive_member_bytes(dataset: dict[str, Any], raw_dir: Path) -> bytes:
    """Extract the canonical PLY bytes from a manifest-described archive."""
    archive = raw_dir / manifest_path_component(dataset["filename"], "filename")
    if not archive.exists():
        raise FileNotFoundError(f"raw archive missing: {archive}")
    archive_type = str(dataset["archive_type"])
    inner_path = str(dataset["inner_path"])
    if archive_type == "tar.gz":
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.extractfile(inner_path)
            if member is None:
                raise FileNotFoundError(f"{inner_path} not found in {archive}")
            return member.read()
    if archive_type == "gz":
        with gzip.open(archive, "rb") as handle:
            return handle.read()
    raise ValueError(f"unsupported archive_type: {archive_type}")


def bounds(points: list[Point]) -> tuple[Point, Point]:
    """Return axis-aligned bounds for processed metadata."""
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    lo = tuple(min(point[axis] for point in points) for axis in range(3))
    hi = tuple(max(point[axis] for point in points) for axis in range(3))
    return lo, hi


def write_ascii_ply(path: Path, points: list[Point]) -> None:
    """Write point-only ASCII PLY accepted by src/cli/rch_order.cpp.

    Coordinates are declared as `double` and written with 17 significant
    digits so binary64 values round-trip through the ASCII canonical form.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write("comment generated_by scripts/convert_dataset.py\n")
        handle.write(f"element vertex {len(points)}\n")
        handle.write("property double x\nproperty double y\nproperty double z\n")
        handle.write("end_header\n")
        for x, y, z in points:
            if not all(math.isfinite(value) for value in (x, y, z)):
                raise ValueError(f"non-finite point cannot be written to {path}")
            handle.write(f"{x:.17g} {y:.17g} {z:.17g}\n")


def convert_dataset(
    dataset: dict[str, Any], raw_dir: Path, processed_dir: Path
) -> Path:
    """Convert one manifest dataset and emit sidecar metadata JSON."""
    dataset_id = manifest_path_component(dataset["id"], "id")
    source_bytes = archive_member_bytes(dataset, raw_dir)
    points, header = read_ply_points(source_bytes)
    expected = int(dataset.get("expected_vertices", len(points)))
    if len(points) != expected:
        raise ValueError(
            f"{dataset_id} vertex count mismatch: expected {expected}, got {len(points)}"
        )

    output = processed_dir / f"{dataset_id}.ply"
    write_ascii_ply(output, points)
    lo, hi = bounds(points)
    metadata = {
        "schema": "rch.processed_dataset.v1",
        "dataset_id": dataset_id,
        "label": dataset.get("label", dataset_id),
        "source_filename": dataset["filename"],
        "source_inner_path": dataset["inner_path"],
        "source_ply_format": header.fmt,
        "source_sha256": sha256_bytes(source_bytes),
        "archive_sha256": dataset["sha256"],
        "processed_path": str(output),
        "processed_sha256": sha256_file(output),
        "vertex_count": len(points),
        "bbox_min": list(lo),
        "bbox_max": list(hi),
    }
    output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return output


def convert_manifest(args: argparse.Namespace) -> list[Path]:
    """Facade used by CLI and tests; converts selected manifest datasets."""
    manifest = load_manifest(args.manifest)
    wanted = set(args.dataset) if args.dataset else None
    converted: list[Path] = []
    for dataset in manifest["datasets"]:
        if wanted is not None and str(dataset["id"]) not in wanted:
            continue
        converted.append(
            convert_dataset(dict(dataset), args.raw_dir, args.processed_dir)
        )
    if wanted is not None and len(converted) != len(wanted):
        present = {Path(path).stem for path in converted}
        missing = sorted(wanted - present)
        raise ValueError(f"datasets not converted: {', '.join(missing)}")
    return converted


def parse_args() -> argparse.Namespace:
    """Parse the Real converter CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "data/manifests/stanford_3d_scanning.yml",
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=REPO_ROOT / "data/raw/stanford_3d_scanning"
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=REPO_ROOT / "data/processed/stanford_3d_scanning",
    )
    parser.add_argument("--dataset", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    """Convert all requested canonical PLY files."""
    for path in convert_manifest(parse_args()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
