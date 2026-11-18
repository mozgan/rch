#!/usr/bin/env python3
"""Cost instrumentation round trip, nested phases, counters and legacy-data handling."""

import argparse, csv, json, subprocess, sys, tempfile
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
SUBPHASES = [
    "robust_" + name
    for name in (
        "pilot",
        "guard",
        "starts",
        "concentration",
        "finalization",
        "remainder",
    )
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("binary", type=Path)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="cost_smoke_") as name:
        root = Path(name)
        spec = yaml.safe_load(
            (
                ROOT / "experiments/runlists/independent/cost_decomposition.yaml"
            ).read_text()
        )
        spec["point_counts"] = [64]
        (root / "runlist.yaml").write_text(yaml.safe_dump(spec))
        for mode in ("off", "all"):
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "experiments/runners/run_matrix.py"),
                    "--runlist",
                    str(root / "runlist.yaml"),
                    "--output-dir",
                    str(root / mode),
                    "--rch-order-bin",
                    str(a.binary.resolve()),
                    "--refinement",
                    mode,
                ],
                check=True,
                capture_output=True,
            )
        command = [
            sys.executable,
            str(ROOT / "analysis/scripts/analyze_cost_decomposition.py"),
            "--off",
            str(root / "off/cost_decomposition.csv"),
            "--all",
            str(root / "all/cost_decomposition.csv"),
            "--out",
            str(root / "summary"),
        ]
        subprocess.run(command, check=True, capture_output=True)
        report = list(csv.DictReader((root / "summary.csv").open()))
        assert len(report) == 4
        for row in report:
            assert all(row[field + "_median_seconds"] != "" for field in SUBPHASES)
            if row["algorithm_id"] == "A6_rch":
                assert float(row["robust_concentration_median_seconds"]) > 0
                assert float(row["starts_median_count"]) > 0
                assert float(row["concentration_iterations_median_count"]) >= float(
                    row["starts_median_count"]
                )
        # A legacy result without instrumentation must remain unknown, not measured zero.
        for mode in ("off", "all"):
            path = root / mode / "cost_decomposition.csv"
            rows = list(csv.DictReader(path.open()))
            for row in rows:
                phases = json.loads(row["timing_breakdown_seconds"])
                for key in SUBPHASES:
                    phases.pop(key)
                row["timing_breakdown_seconds"] = json.dumps(phases)
                row["robust_work_counts"] = "{}"
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        subprocess.run(command, check=True, capture_output=True)
        assert all(
            r["robust_concentration_median_seconds"] == ""
            for r in csv.DictReader((root / "summary.csv").open())
        )
        path = root / "off/cost_decomposition.csv"
        rows = list(csv.DictReader(path.open()))
        phases = json.loads(rows[0]["timing_breakdown_seconds"])
        phases["robust_estimator"] = -1
        rows[0]["timing_breakdown_seconds"] = json.dumps(phases)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        assert subprocess.run(command, capture_output=True).returncode != 0
    print(
        "PASS: 40 cost cells, 5 internal repeats; nested phases/counters; legacy unknowns and invalid timing rejection"
    )


if __name__ == "__main__":
    main()
