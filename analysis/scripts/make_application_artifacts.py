#!/usr/bin/env python3
"""Generate application figures/tables from strictly validated current measurements."""

from __future__ import annotations

import argparse
import math
import csv
import json
import shutil
import statistics
from pathlib import Path

import matplotlib
import yaml

matplotlib.use("Agg")
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analysis.scripts.analyze_application_query_metrics import analyze, digest


def generate(source: Path, output: Path, real_results: Path | None = None) -> None:
    tables, figures, stats = [output / name for name in ("tables", "figures", "stats")]
    for directory in (tables, figures, stats):
        directory.mkdir(parents=True, exist_ok=True)
    manifest_path = source / "run_manifest.json"
    if not manifest_path.exists():
        snapshot = output / "outputs/application_query"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        text = "The full application-query matrix has not been generated. No query performance result is claimed."
        (tables / "table_application_query.tex").write_text(text + "\n")
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.axis("off")
        ax.text(0.05, 0.5, text, wrap=True)
        fig.savefig(figures / "fig_application_query_latency.pdf", bbox_inches="tight")
        plt.close(fig)
        (stats / "application_artifacts_manifest.json").write_text(
            json.dumps({"status": "unavailable_full_matrix"}) + "\n"
        )
        return
    # Revalidate raw data and all checksums; never rely on an old summary.
    import tempfile

    with tempfile.TemporaryDirectory() as temp:
        specification = json.loads(manifest_path.read_text())
        repeats = specification["cache_protocol"]["measured_workload_repeats"]
        if repeats < 5:
            raise ValueError("publication artifacts require at least five repeats")
        report = analyze(source, Path(temp) / "validated", expected_repeats=repeats)
        snapshot = output / "outputs/application_query"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        snapshot.mkdir(parents=True, exist_ok=True)
        for file in (Path(temp) / "validated").iterdir():
            shutil.copy2(file, snapshot / file.name)
    manifest = json.loads(manifest_path.read_text())
    layout_note = (
        " RCH/C3 is the default native rule; RCH/C0 remains a control."
        if "A6_rch_C3" in report["layouts"]
        else ""
    )
    lines = [
        r"\begin{table}[tbp]\centering\small",
        r"\caption{Warm-cache exact window queries on fixed point-cloud datasets. Latencies are raw-sample percentiles. Full scan reads every page; other layouts use the common page directory."
        + layout_note
        + "}",
        r"\label{tab:application_query}",
        r"\begin{tabular}{llrrr}\toprule Dataset & Layout & p50 (ms) & p95 (ms) & Read pages \\ \midrule",
    ]
    for r in report["summaries"]:
        lines.append(
            f"{r['dataset_id'].removeprefix('stanford_').replace('_', ' ').title()} & {r['layout_id'].replace('_', chr(92) + '_')} & {1000 * r['p50_wall_seconds']:.4g} & {1000 * r['p95_wall_seconds']:.4g} & {r['mean_pages_read']:.1f} "
            + r"\\"
        )
    lines += [r"\bottomrule\end{tabular}\end{table}"]
    lines += [
        r"\begin{table}[tbp]\centering\small",
        r"\caption{Paired mean query latency difference against isotropic Hilbert (RCH variants minus A3). Intervals are pointwise and resample query IDs within each fixed dataset; preparation timing uncertainty is excluded.}",
        r"\label{tab:application_paired}",
        r"\begin{tabular}{llrrr}\toprule Dataset & Layout & Difference (ms) & 95\% interval (ms) & Break-even queries \\ \midrule",
    ]
    for r in report["paired_comparisons"]:
        if (
            r["layout_id"].startswith("A6_rch")
            and r["reference"] == "A3_isotropic_hilbert"
        ):
            count = (
                "--"
                if r["break_even_queries"] is None
                else f"{r['break_even_queries']:.3g}"
            )
            lines.append(
                f"{r['dataset_id'].removeprefix('stanford_').replace('_', ' ').title()} & {r['layout_id'].replace('_', chr(92) + '_')} & {1000 * r['mean_delta_seconds']:.4g} & [{1000 * r['ci95_low_seconds']:.4g}, {1000 * r['ci95_high_seconds']:.4g}] & {count} "
                + r"\\"
            )
    lines += [r"\bottomrule\end{tabular}\end{table}"]
    (tables / "table_application_query.tex").write_text("\n".join(lines) + "\n")
    columns = min(4, len(manifest["datasets"]))
    rows = math.ceil(len(manifest["datasets"]) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(4 * columns, 4 * rows), squeeze=False)
    for ax, d in zip(axes.flat, manifest["datasets"]):
        rows = [r for r in report["summaries"] if r["dataset_id"] == d["dataset_id"]]
        ax.bar(range(len(rows)), [r["p50_wall_seconds"] * 1000 for r in rows])
        display = {
            "A0_input": "Input",
            "A0_full_scan": "Full scan",
            "A3_isotropic_hilbert": "Hilbert C0",
            "A6_rch": "RCH C0",
            **{f"A6_rch_C{n}": f"RCH C{n}" for n in (2, 3, 4)},
        }
        ax.set_xticks(
            range(len(rows)),
            [display[r["layout_id"]] for r in rows],
            rotation=40,
            ha="right",
        )
        ax.set_title(d["dataset_id"])
        ax.set_ylabel("Warm-cache p50 latency (ms)")
    for ax in list(axes.flat)[len(manifest["datasets"]):]:
        ax.set_visible(False)
    fig.tight_layout()
    fig.savefig(figures / "fig_application_query_latency.pdf")
    plt.close(fig)
    # Data/geometry/phase/overhead details remain machine-readable and source-linked.
    (snapshot / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name, rows in [
        (
            "geometry",
            [
                {"dataset_id": d["dataset_id"], **d["geometry"]}
                for d in manifest["datasets"]
            ],
        ),
        (
            "ordering_phases",
            [
                {
                    "dataset_id": d["dataset_id"],
                    "layout_id": layout,
                    "sort_seconds": v.get("sort_seconds", 0),
                    "timing_repeats": v.get("timing_repeats", 0),
                    **v.get("timing_breakdown_seconds", {}),
                }
                for d in manifest["datasets"]
                for layout, v in d["ordering_diagnostics"].items()
            ],
        ),
    ]:
        with (snapshot / f"{name}.csv").open("w", newline="") as handle:
            w = csv.DictWriter(
                handle, fieldnames=list(dict.fromkeys(k for row in rows for k in row))
            )
            w.writeheader()
            w.writerows(rows)
    with (snapshot / "quantization_diagnostics.csv").open("w", newline="") as handle:
        fields = (
            "dataset_id",
            "layout_id",
            "bit_rule",
            "bit_allocator",
            "resolved_bits_axis",
            "domain_half_extents",
            "frame_mode",
            "robust_fallback_used",
            "outside_core_fraction",
            "clipped_fraction",
            "duplicate_key_fraction",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: r[field] for field in fields} for r in report["summaries"]
        )
    real_phases = []
    if real_results is not None:
        for mode in ("off", "all"):
            for file in sorted(
                (real_results / mode / "manifests").glob("*.manifest.json")
            ):
                parts = file.name.split("__")
                if (
                    len(parts) < 4
                    or parts[1]
                    not in ("A3_isotropic_hilbert", "A5_pca_compact_hilbert", "A6_rch")
                    or parts[2] != "C3_frame_core_occupancy"
                    or parts[3] != "D0"
                ):
                    continue
                record = json.loads(file.read_text())
                if "timing_breakdown_seconds" in record:
                    real_phases.append(
                        {
                            "dataset_id": parts[0],
                            "layout_id": parts[1],
                            "refinement_mode": mode,
                            "seed": parts[-1].split(".")[0],
                            "sort_seconds": record["sort_seconds"],
                            **record["timing_breakdown_seconds"],
                            "source_manifest": str(file),
                            "source_manifest_sha256": digest(file),
                        }
                    )
        if real_phases:
            with (snapshot / "real_refinement_phases.csv").open(
                "w", newline=""
            ) as handle:
                w = csv.DictWriter(handle, fieldnames=list(real_phases[0]))
                w.writeheader()
                w.writerows(real_phases)
    if real_results is not None:
        groups = {}
        for row in real_phases:
            key = (row["dataset_id"], row["layout_id"], row["refinement_mode"])
            groups.setdefault(key, []).append(row)
        expected = {
            (dataset, layout, mode)
            for dataset in yaml.safe_load(
                (
                    Path(__file__).resolve().parents[2]
                    / "experiments/runlists/table_2_dataset_summary.yaml"
                ).read_text()
            )["dataset_ids"]
            for layout in ("A3_isotropic_hilbert", "A5_pca_compact_hilbert", "A6_rch")
            for mode in ("off", "all")
        }
        if set(groups) != expected or any(
            {r["seed"] for r in records} != {f"s{i}" for i in range(5)}
            or len(records) != 5
            for records in groups.values()
        ):
            raise ValueError(
                "real C3 refinement phase matrix incomplete; rerun bench-real with current CLI and default five seeds/off+all modes"
            )
        summary = []
        for (dataset, layout, mode), records in sorted(groups.items()):
            summary.append(
                {
                    "dataset_id": dataset,
                    "layout_id": layout,
                    "refinement_mode": mode,
                    "repeated_measurements": len(records),
                    **{
                        f"{field}_median_seconds": statistics.median(
                            float(r[field]) for r in records
                        )
                        for field in records[0]
                        if field
                        not in (
                            "dataset_id",
                            "layout_id",
                            "refinement_mode",
                            "seed",
                            "source_manifest",
                            "source_manifest_sha256",
                        )
                    },
                }
            )
        with (snapshot / "real_refinement_phase_summary.csv").open(
            "w", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
    measured_rules = "The shared application matrix includes distinct C0/C2/C3/C4 RCH layouts."
    evidence = [
        "# Application query evidence",
        "",
        "R1.1: Exact page-file query, disk full-scan control, payload compression, logical bytes and available OS counters are measured. These results concern warm-cache queries on fixed datasets, including reconstruction meshes and a USGS airborne LiDAR tile.",
        "R2.3: Whole-dataset PCA geometry descriptors and ordering clamping diagnostics are recorded. The tested fixed datasets do not establish a general failure regime.",
        "R2.4: Each measured ordering layout uses five in-process repeats. "
        + measured_rules
        + " Native rules do not share controlled physical resolution. Separate C3 real-data off/all phase records, when present, are supplied in real_refinement_phases.csv; fixed seed labels are repeated measurements, not independent datasets. Preparation amortization is conditional on the measured workload. RSS is cumulative process memory, not isolated layout memory.",
        "R2.5: Common page-directory comparisons do not establish superiority over tree indexes or database systems.",
        "",
        "Paired mean latency differences (layout minus reference), with within-dataset query bootstrap intervals:",
        "",
    ]
    for r in report["paired_comparisons"]:
        evidence.append(
            f"- {r['dataset_id']}: {r['layout_id']} vs {r['reference']}: {r['mean_delta_seconds']:.6g} s [{r['ci95_low_seconds']:.6g}, {r['ci95_high_seconds']:.6g}]; break-even queries: {r['break_even_queries']}"
        )
    (snapshot / "evidence.md").write_text("\n".join(evidence) + "\n")
    (stats / "application_artifacts_manifest.json").write_text(
        json.dumps(
            {
                "status": "validated_full_matrix",
                "source_manifest_sha256": digest(manifest_path),
                "generator_sha256": digest(Path(__file__)),
                "artifacts": {
                    str(p.relative_to(output)): digest(p)
                    for p in [
                        tables / "table_application_query.tex",
                        figures / "fig_application_query_latency.pdf",
                        *sorted(snapshot.glob("*")),
                    ]
                    if p.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("analysis/generated"))
    parser.add_argument("--real-results-dir", type=Path)
    args = parser.parse_args()
    generate(args.input_root, args.output_root, args.real_results_dir)
