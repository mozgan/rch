#!/usr/bin/env python3
"""Preserve current sources and generated results outside cleanup roots."""

import argparse
import hashlib
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

UTC = timezone.utc  # noqa: UP017 -- Python 3.10 compatibility

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--output-dir", type=Path, default=ROOT / "backups/sources")
a = p.parse_args()
a.output_dir = a.output_dir.resolve()
if not a.output_dir.is_relative_to(ROOT / "backups"):
    raise ValueError("backup directory must be under the repository's backups directory")
a.output_dir.mkdir(parents=True, exist_ok=True)
path = a.output_dir / f"rch_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}.tar.gz"
with tarfile.open(path, "x:gz") as archive:
    for name in (
        "Makefile",
        "CMakeLists.txt",
        "CMakePresets.json",
        "requirements.txt",
        "include",
        "src",
        "tests",
        "scripts",
        "experiments",
        "analysis",
        "paper",
        "data",
    ):
        source = ROOT / name
        if source.exists():
            archive.add(
                source,
                arcname=name,
                filter=lambda info: (
                    None if "__pycache__" in info.name.split("/") else info
                ),
            )
h = hashlib.sha256()
with path.open("rb") as handle:
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        h.update(block)
path.with_suffix(path.suffix + ".sha256").write_text(f"{h.hexdigest()}  {path.name}\n")
print(path)
