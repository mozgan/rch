#!/usr/bin/env python3
"""Short scientific pipeline: independent families, paired metrics, stale/tampered rejection."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis/scripts"))
from data.synthetic.generators.regime import regime_points, FAMILIES, SHAPES
from analyze_regime_benchmarks import validate, miad, descriptors


def main():
    p = argparse.ArgumentParser()
    p.add_argument("binary", type=Path)
    a = p.parse_args()
    for family in FAMILIES:
        for shape in SHAPES:
            points = regime_points(32, family, shape, 123)
            assert np.isfinite(points).all() and len(points) == 32
            assert points == regime_points(32, family, shape, 123)
            assert points != regime_points(32, family, shape, 124)
    assert (
        descriptors(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]))[
            "sample_axis_aspect"
        ]
        is None
    )
    assert (
        miad(np.array([[0.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.0, 4.0, 12.0]]), [0, 1, 2])
        == 8.5
    )
    with tempfile.TemporaryDirectory(
        dir=ROOT / "build", prefix="regime_smoke_"
    ) as name:
        root = Path(name)
        primary = yaml.safe_load(
            (ROOT / "experiments/runlists/independent/regime_map.yaml").read_text()
        )
        primary.update(
            name="regime_smoke",
            geometry_ids=["R_volume_isotropic", "R_surface_prolate"],
            point_counts=[32],
            seeds=[0, 1],
        )
        sensitivity = dict(
            primary,
            name="regime_size_smoke",
            geometry_ids=["R_curve_triaxial"],
            point_counts=[48],
            seeds=[20],
        )
        for label, spec in [("primary", primary), ("sensitivity", sensitivity)]:
            (root / (label + ".yaml")).write_text(yaml.safe_dump(spec))
        command = [
            sys.executable,
            str(ROOT / "experiments/runners/run_regime_benchmarks.py"),
            "--output-dir",
            str(root / "run"),
            "--rch-order-bin",
            str(a.binary.resolve()),
            "--primary-runlist",
            str(root / "primary.yaml"),
            "--sensitivity-runlist",
            str(root / "sensitivity.yaml"),
            "--bootstrap-resamples",
            "100",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        manifest, records = validate(root / "run")
        assert len(records) == 300
        assert all(
            r["kendall_tau_clean"] == 1
            for r in records
            if r["contamination_id"] == "D0"
        )
        analyzer = [
            sys.executable,
            str(ROOT / "analysis/scripts/analyze_regime_benchmarks.py"),
            "--input-root",
            str(root / "run"),
            "--output-dir",
            str(root / "report"),
            "--artifact-root",
            str(root / "artifacts"),
            "--bootstrap-resamples",
            "100",
        ]
        subprocess.run(analyzer, check=True, capture_output=True)
        subprocess.run(analyzer + ["--validate-only"], check=True, capture_output=True)
        # Independent O(n^2) inlier Kendall for every method/rule/condition in the fixture.
        from run_matrix import read_order_csv

        for study, spec in [("primary", primary), ("size_sensitivity", sensitivity)]:
            directory = root / "run" / study
            for r in csv.DictReader((directory / (spec["name"] + ".csv")).open()):
                stem = f"{r['algorithm_id']}__{r['bit_rule']}__{r['contamination_id']}__{r['geometry_id']}__n{r['clean_point_count']}__s{r['seed']}"
                n = int(r["clean_point_count"])
                cleanstem = stem.replace("__" + r["contamination_id"] + "__", "__D0__")
                clean = read_order_csv(
                    directory / "orders" / (cleanstem + ".order.csv")
                )
                order = [
                    i
                    for i in read_order_csv(
                        directory / "orders" / (stem + ".order.csv")
                    )
                    if i < n
                ]
                rank = {id_: i for i, id_ in enumerate(clean)}
                inv = sum(
                    rank[order[i]] > rank[order[j]]
                    for i in range(n)
                    for j in range(i + 1, n)
                )
                assert (
                    abs(1 - 4 * inv / (n * (n - 1)) - float(r["kendall_tau_clean"]))
                    < 1e-12
                )
        # Reject incorrect metric even if the source checksum is maliciously refreshed.
        path = root / "run/primary/regime_smoke.csv"
        cells = list(csv.DictReader(path.open()))
        cells[0]["miad"] = "999"
        with path.open("w", newline="") as stream:
            w = csv.DictWriter(stream, fieldnames=list(cells[0]))
            w.writeheader()
            w.writerows(cells)
        manifest["files_sha256"]["primary/regime_smoke.csv"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        (root / "run/run_manifest.json").write_text(json.dumps(manifest))
        try:
            validate(root / "run")
        except ValueError:
            pass
        else:
            raise AssertionError("incorrect scientific metric accepted")
    print(
        "PASS: 16 family/shape generators; 300 paired CLI cells; independent Kendall; tampered MIAD rejected"
    )


if __name__ == "__main__":
    main()
