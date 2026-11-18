#!/usr/bin/env python3
"""Run every independent benchmark matrix and its existing evidence analyzers."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--rch-order-bin", required=True)
    p.add_argument("--cgal-adapter-bin", required=True)
    p.add_argument("--analyze-only", action="store_true")
    a = p.parse_args()
    root = a.output_dir.resolve()
    if not a.analyze_only:
        root.mkdir(parents=True, exist_ok=False)

    def run(script: str, *args: str) -> None:
        subprocess.run([sys.executable, script, *map(str, args)], check=True, cwd=ROOT)

    experiments = [
        ("table_3_locality", "off"),
        ("table_4_outlier", "off"),
        ("frame_ablation_fixed_domain", "off"),
        ("frame_ablation_bit_rules", "off"),
        ("cost_decomposition", "off"),
        ("cost_decomposition", "all"),
        ("pca_fixed_hilbert_control", "off"),
    ]
    outputs = {}
    for name, mode in experiments:
        runlist = ROOT / f"experiments/runlists/independent/{name}.yaml"
        label = yaml.safe_load(runlist.read_text())["name"]
        directory = root / name / mode
        outputs[(name, mode)] = directory / f"{label}.csv"
        if not a.analyze_only:
            run(
                "experiments/runners/run_matrix.py",
                "--runlist",
                str(runlist),
                "--output-dir",
                str(directory),
                "--rch-order-bin",
                a.rch_order_bin,
                "--cgal-adapter-bin",
                a.cgal_adapter_bin,
                "--refinement",
                mode,
            )
    if not a.analyze_only:
        run("experiments/runners/run_regime_benchmarks.py",
            "--output-dir", root / "regime_map", "--rch-order-bin", a.rch_order_bin)
    else:
        run("analysis/scripts/analyze_regime_benchmarks.py",
            "--input-root", root / "regime_map", "--output-dir", root / "regime_map/reports")
    report = root / "reports"
    stability_root = root / "frame_stability"
    if not a.analyze_only:
        run(
            "experiments/runners/run_frame_stability.py",
            "--natural-results", outputs[("frame_ablation_bit_rules", "off")],
            "--runlist", ROOT / "experiments/runlists/independent/frame_ablation_bit_rules.yaml",
            "--rch-order-bin", a.rch_order_bin,
            "--output-dir", stability_root,
        )
    run(
        "analysis/scripts/analyze_frame_stability.py",
        "--input-root", stability_root,
        "--output-dir", report / "frame_stability",
    )
    run(
        "analysis/scripts/analyze_independent_samples.py",
        "--locality-results",
        outputs[("table_3_locality", "off")],
        "--stability-results",
        outputs[("table_4_outlier", "off")],
        "--output-dir",
        report / "independent",
    )
    run(
        "analysis/scripts/analyze_frame_ablation.py",
        "--fixed-domain-results",
        outputs[("frame_ablation_fixed_domain", "off")],
        "--policy-results",
        outputs[("frame_ablation_bit_rules", "off")],
        "--output-dir",
        report / "frame_ablation",
    )
    run(
        "analysis/scripts/analyze_clamping_diagnostics.py",
        "--results",
        outputs[("table_4_outlier", "off")],
        "--output-dir",
        report / "clamping",
    )
    run(
        "analysis/scripts/analyze_cost_decomposition.py",
        "--off",
        outputs[("cost_decomposition", "off")],
        "--all",
        outputs[("cost_decomposition", "all")],
        "--out",
        report / "cost/summary",
    )
    run(
        "analysis/scripts/analyze_pca_fixed_hilbert_control.py",
        "--input",
        outputs[("pca_fixed_hilbert_control", "off")],
        "--output",
        report / "pca_fixed/summary",
    )
    inventory = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "benchmark_manifest.json"
    }
    (root / "benchmark_manifest.json").write_text(
        json.dumps(
            {
                "schema": "rch.independent_benchmarks.v1",
                "platform": platform.platform(),
                "python": sys.version,
                "files_sha256": inventory,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
