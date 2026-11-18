#!/usr/bin/env python3
"""Run the frozen geometry/shape/contamination matrix and separate size sensitivity."""

from __future__ import annotations
import argparse
import hashlib
import json
import platform
import numpy as np
import yaml
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rch-order-bin", type=Path, required=True)
    p.add_argument(
        "--primary-runlist",
        type=Path,
        default=ROOT / "experiments/runlists/independent/regime_map.yaml",
    )
    p.add_argument(
        "--sensitivity-runlist",
        type=Path,
        default=ROOT
        / "experiments/runlists/independent/regime_map_size_sensitivity.yaml",
    )
    p.add_argument("--bootstrap-resamples", type=int, default=5000)
    a = p.parse_args()
    root = a.output_dir.resolve()
    binary = a.rch_order_bin.resolve()
    root.mkdir(parents=True, exist_ok=False)
    binary_hash = digest(binary)
    sources = [
        "data/synthetic/generators/regime.py",
        "experiments/runners/run_matrix.py",
        "experiments/runners/run_regime_benchmarks.py",
        "analysis/scripts/analyze_regime_benchmarks.py",
        "data/synthetic/generators/common.py",
        "data/synthetic/generators/gaussian_ellipsoid.py",
        "data/synthetic/generators/contamination.py",
        "experiments/configs/sweeps/contamination.yaml",
        "experiments/configs/sweeps/refinement.yaml",
        *[
            "experiments/configs/algorithms/" + a + ".yaml"
            for a in ("A3_isotropic_hilbert", "A5_pca_compact_hilbert", "A6_rch")
        ],
    ]
    source_hashes = {name: digest(ROOT / name) for name in sources}
    for label, source in [
        ("primary", a.primary_runlist),
        ("size_sensitivity", a.sensitivity_runlist),
    ]:
        (root / (label + ".yaml")).write_bytes(source.read_bytes())
    for label, source in [
        ("primary", a.primary_runlist),
        ("size_sensitivity", a.sensitivity_runlist),
    ]:
        snapshot = root / (label + ".yaml")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "experiments/runners/run_matrix.py"),
                "--runlist",
                str(snapshot),
                "--output-dir",
                str(root / label),
                "--rch-order-bin",
                str(binary),
                "--refinement",
                "off",
            ],
            check=True,
            cwd=ROOT,
        )
    if digest(binary) != binary_hash:
        raise ValueError("binary changed during regime experiment")
    files = {
        str(p.relative_to(root)): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    if source_hashes != {name: digest(ROOT / name) for name in sources}:
        raise ValueError("regime source code changed during run")
    manifest = dict(
        schema="rch.regime_benchmarks.v1",
        environment=dict(
            platform=platform.platform(),
            python=sys.version,
            numpy=np.__version__,
            pyyaml=yaml.__version__,
        ),
        binary_sha256=binary_hash,
        files_sha256=files,
        source_sha256=source_hashes,
        scope="Predeclared exploratory geometry strata, no trained or externally validated selector; size sensitivity has different seeds and limited shapes",
    )
    (root / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "analysis/scripts/analyze_regime_benchmarks.py"),
            "--input-root",
            str(root),
            "--output-dir",
            str(root / "reports"),
            "--bootstrap-resamples",
            str(a.bootstrap_resamples),
        ],
        check=True,
        cwd=ROOT,
    )


if __name__ == "__main__":
    main()
