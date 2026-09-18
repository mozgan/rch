#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# download_dataset.py — Real Dataset manifest-driven downloader
#
# References:
#   - National Institute of Standards and Technology, Secure Hash Standard,
#     2015, DOI: 10.6028/NIST.FIPS.180-4.
#   - Stanford University Computer Graphics Laboratory, The Stanford 3D
#     Scanning Repository, accessed 2026-07-27.
# ----------------------------------------------------------------------------
"""Download real datasets from a checksum-pinned YAML manifest.

Algorithm: select manifest rows, materialize local/remote archive bytes, verify
SHA-256 against the pinned digest, and remove mismatched downloads before
raising an error.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import string
from urllib.parse import urlparse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SHA256_HEX = set(string.hexdigits)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a local file in streaming chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a YAML manifest and fail closed on malformed roots."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("datasets"), list):
        raise ValueError(f"invalid dataset manifest: {path}")
    return data


def selected_datasets(
    manifest: dict[str, Any], dataset_ids: set[str] | None
) -> list[dict[str, Any]]:
    """Filter manifest datasets by id while preserving manifest order."""
    datasets = [dict(item) for item in manifest["datasets"]]
    if dataset_ids is None:
        return datasets
    selected = [item for item in datasets if str(item["id"]) in dataset_ids]
    missing = sorted(dataset_ids - {str(item["id"]) for item in selected})
    if missing:
        raise ValueError(f"datasets not present in manifest: {', '.join(missing)}")
    return selected


def local_source_path(url: str) -> Path | None:
    """Return a local source path for file:// or repo-relative manifest URLs."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError(f"unsupported file URL host: {parsed.netloc}")
        return Path(parsed.path)
    if parsed.scheme == "":
        path = Path(url)
        return path if path.is_absolute() else REPO_ROOT / path
    return None


def manifest_filename(value: object) -> str:
    """Return a safe single filename from a dataset manifest entry."""
    if not isinstance(value, str):
        raise ValueError(f"manifest filename must be a string: {value}")
    filename = value
    path = Path(filename)
    if (
        path.is_absolute()
        or filename in {"", ".", ".."}
        or "/" in filename
        or "\\" in filename
        or len(path.parts) != 1
    ):
        raise ValueError(f"manifest filename must be a plain filename: {filename}")
    return filename


def normalized_sha256(value: object) -> str:
    """Return a lowercase SHA-256 hex digest or fail before any download."""
    if not isinstance(value, str):
        raise ValueError(f"manifest sha256 must be a string: {value}")
    digest = value.lower()
    if len(digest) != 64 or any(char not in SHA256_HEX for char in digest):
        raise ValueError(f"manifest sha256 must be 64 hex characters: {value}")
    return digest


def download_url(url: str, target: Path) -> None:
    """Download `url` to `target` atomically enough for checksum retry."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    local_path = local_source_path(url)
    if local_path is not None:
        shutil.copyfile(local_path, tmp)
    else:
        with urllib.request.urlopen(url, timeout=60) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
    tmp.replace(target)


def ensure_dataset(dataset: dict[str, Any], raw_dir: Path, force: bool = False) -> Path:
    """Ensure one dataset archive exists and matches its manifest SHA-256.

    Flow:
      * Cache hit: target exists, `force` is False, and stored SHA-256
        matches manifest ⇒ no network I/O.
      * Cache miss / force: re-download via `download_url`, recompute
        SHA-256, fail closed if mismatch (target removed before raise).
    Idempotency: `force=False` keeps the operation a no-op on repeat runs.
    """
    target = raw_dir / manifest_filename(dataset["filename"])
    expected = normalized_sha256(dataset["sha256"])
    if target.exists() and not force and sha256_file(target) == expected:
        return target
    download_url(str(dataset["url"]), target)
    actual = sha256_file(target)
    if actual != expected:
        target.unlink(missing_ok=True)
        raise ValueError(
            f"checksum mismatch for {dataset['id']}: expected {expected}, got {actual}"
        )
    return target


def download_manifest(args: argparse.Namespace) -> list[Path]:
    """Facade used by CLI and tests; returns verified raw archive paths."""
    manifest = load_manifest(args.manifest)
    dataset_ids = set(args.dataset) if args.dataset else None
    raw_dir = args.raw_dir
    verified: list[Path] = []
    for dataset in selected_datasets(manifest, dataset_ids):
        verified.append(ensure_dataset(dataset, raw_dir, args.force))
    return verified


def parse_args() -> argparse.Namespace:
    """Parse the Real downloader CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "data/manifests/stanford_3d_scanning.yml",
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=REPO_ROOT / "data/raw/stanford_3d_scanning"
    )
    parser.add_argument("--dataset", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Download and checksum-verify all requested datasets."""
    for path in download_manifest(parse_args()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
