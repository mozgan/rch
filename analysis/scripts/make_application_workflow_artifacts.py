#!/usr/bin/env python3
"""Validate frozen end-to-end measurements and publish descriptive artifacts only."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_workflow import PHASES, digest, validate_run, write_json

NAMES = {"stanford_bunny": "Bunny", "stanford_armadillo": "Armadillo",
         "stanford_dragon": "Dragon", "usgs_cameron_peak": "Cameron Peak",
         "noaa_santiam_river": "Santiam River", "noaa_long_island": "Long Island",
         "noaa_southwest_florida": "Southwest Florida"}
METHODS = {"A0_input": "Input pages", "A3_isotropic_hilbert": "Isotropic Hilbert", "A6_rch_C3": "RCH/C3"}
FIELDS = ("total_seconds", *PHASES, "cpu_seconds", "peak_rss_kib",
          "logical_query_bytes", "storage_read_bytes", "storage_write_bytes")


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summaries(manifest, samples):
    config = manifest["config"]
    summary, paired = [], []
    for dataset in config["datasets"]:
        for count in config["query_counts"]:
            by_layout = {}
            for layout in config["layouts"]:
                selected = sorted([r for r in samples if (r["dataset_id"], r["query_count"], r["layout"]) == (dataset, count, layout)], key=lambda r: r["repeat"])
                by_layout[layout] = selected
                row = {"dataset_id": dataset, "query_count": count, "layout": layout, "repeats": len(selected)}
                for field in FIELDS:
                    values = [r[field] for r in selected if r[field] is not None]
                    row[field + "_available"] = len(values)
                    # An incomplete counter series is not silently summarized from a subset.
                    row[field + "_median"] = statistics.median(values) if len(values) == len(selected) else ""
                total = [r["total_seconds"] for r in selected]
                quartiles = statistics.quantiles(total, n=4, method="inclusive") if len(total) > 1 else total * 3
                row.update(total_seconds_q1=quartiles[0], total_seconds_q3=quartiles[2])
                summary.append(row)
            reference = by_layout["A3_isotropic_hilbert"]
            for layout in config["layouts"]:
                differences = [r["total_seconds"] - b["total_seconds"] for r, b in zip(by_layout[layout], reference)]
                paired.append({"dataset_id": dataset, "query_count": count, "layout": layout,
                               "reference": "A3_isotropic_hilbert", "paired_repeats": len(differences),
                               "median_paired_total_seconds": statistics.median(differences),
                               "scope": "fixed input and nested query workload; paired by workflow repeat; descriptive only"})
    return summary, paired


def generate(source, generated, validate_only=False):
    source, generated = Path(source).resolve(), Path(generated).resolve()
    manifest, samples = validate_run(source)
    destination = generated / "outputs/application_workflow"
    proof_path = destination / "analysis_manifest.json"
    if validate_only:
        proof = json.loads(proof_path.read_text())
        if proof["source_manifest_sha256"] != digest(source / "run_manifest.json") or proof["generator_sha256"] != digest(Path(__file__)):
            raise ValueError("workflow artifacts have stale source/generator")
        for name, checksum in proof["artifacts_sha256"].items():
            path = (generated / name).resolve()
            path.relative_to(generated)
            if digest(path) != checksum:
                raise ValueError("workflow published artifact checksum mismatch")
        return
    for directory in (destination, generated / "tables", generated / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    summary, paired = summaries(manifest, samples)
    write_csv(destination / "measurements.csv", samples)
    write_csv(destination / "summary.csv", summary)
    write_csv(destination / "paired_comparisons.csv", paired)
    write_json(destination / "source_manifest.json", manifest)
    index = {(r["dataset_id"], r["query_count"], r["layout"]): r for r in summary}
    pair_index = {(r["dataset_id"], r["query_count"], r["layout"]): r for r in paired}
    lines = [r"\begin{tabular}{lrrrrr}",
             r"Input & Queries & Input (s) & Hilbert (s) & RCH (s) & Paired $\Delta$ (s) \\", r"\hline"]
    io_lines = [r"\begin{tabular}{lrrrrr}",
                r"Input & Queries & Hilbert read & Hilbert write & RCH read & RCH write \\", r"\hline"]
    def mib(value):
        return "--" if value == "" else f"{value / 1048576:.3f}"
    for dataset in manifest["config"]["datasets"]:
        for count in manifest["config"]["query_counts"]:
            name = NAMES.get(dataset, dataset.replace("_", r"\_"))
            times = [index[dataset, count, layout]["total_seconds_median"] for layout in manifest["config"]["layouts"]]
            delta = pair_index[dataset, count, "A6_rch_C3"]["median_paired_total_seconds"]
            lines.append(name + f" & {count} & " + " & ".join(f"{v:.4f}" for v in times) + f" & {delta:+.4f}" + r" \\")
            ios = [mib(index[dataset, count, layout][field + "_median"])
                   for layout in ("A3_isotropic_hilbert", "A6_rch_C3")
                   for field in ("storage_read_bytes", "storage_write_bytes")]
            io_lines.append(name + f" & {count} & " + " & ".join(ios) + r" \\")
    table = generated / "tables/table_application_workflow.tex"
    io_table = generated / "tables/table_application_workflow_io.tex"
    table.write_text("\n".join(lines + [r"\end{tabular}"]) + "\n")
    io_table.write_text("\n".join(io_lines + [r"\end{tabular}"]) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    datasets = manifest["config"]["datasets"]
    fig, axes = plt.subplots((len(datasets) + 2) // 3, 3, figsize=(12, 3.4 * ((len(datasets) + 2) // 3)), squeeze=False, layout="constrained")
    for ax, dataset in zip(axes.flat, datasets):
        counts = sorted(manifest["config"]["query_counts"])
        for layout in manifest["config"]["layouts"]:
            ax.plot(counts, [index[dataset, q, layout]["total_seconds_median"] for q in counts], marker="o", label=METHODS[layout])
        ax.set_title(NAMES.get(dataset, dataset))
        ax.set_xlabel("Queries per workflow")
        ax.set_ylabel("Median complete workflow (s)")
        ax.set_xticks(counts)
        ax.grid(alpha=.25)
    for ax in list(axes.flat)[len(datasets):]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=8)
    figure = generated / "figures/fig_application_workflow.pdf"
    fig.savefig(figure, metadata={"CreationDate": None})
    plt.close(fig)
    subprocess.run(["pdftops", "-eps", str(figure), str(figure.with_suffix(".eps"))], check=True)
    (destination / "scope.md").write_text(
        "# Continuous storage/query workflow\n\n"
        "Total wall time is directly measured, not a sum of independent medians. "
        "One ordering call per fresh process; refinement off; file and directory fsync included. "
        "Input warming/mincore, oracle preparation/load, process startup, and post-run verification are excluded. "
        "Queries share naturally cached newly written pages; this is not the separate cold-page experiment.\n\n"
        "Prepared XYZ is the starting input; download and source conversion are excluded. "
        "This is storage/query processing, not a downstream scientific application. "
        "Repeated workflows and nested query prefixes are not independent scenes. "
        "Tables show descriptive medians, with no population inference or significance claim. "
        "Paired differences use the same repeat number; phase medians need not sum to median total time.\n\n"
        "I/O is process-attributed Linux read_bytes/write_bytes, not device telemetry. "
        "Writes may include filesystem accounting effects. Missing counters are --, never zero. "
        "I/O table units are MiB (1048576 bytes); all values are medians of workflow totals. "
        "Peak RSS covers this fresh process through the workflow, including pre-timer workload loading and input-cache setup; "
        "CPU snapshots slightly bracket the steady-clock interval.\n\n"
        "Bulk outputs are independently checked against materialized result hashes before optional cleanup. "
        "Frozen inputs, oracle workloads, source snapshots, metrics, logs, output sizes and checksums remain.\n"
    )
    files = [*destination.glob("*.csv"), destination / "source_manifest.json", destination / "scope.md",
             table, io_table, figure, figure.with_suffix(".eps")]
    write_json(proof_path, {"schema": "rch.application_workflow.artifacts.v1",
                          "source_manifest_sha256": digest(source / "run_manifest.json"),
                          "generator_sha256": digest(Path(__file__)),
                          "artifacts_sha256": {str(p.relative_to(generated)): digest(p) for p in files}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "experiments/outputs/application_workflow/full_benchmark")
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "analysis/generated")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    generate(args.input_root, args.artifact_root, args.validate_only)
    print("Workflow artifact validation passed" if args.validate_only else "Workflow artifacts generated from validated measurements")


if __name__ == "__main__":
    main()
