#!/usr/bin/env python3
"""Publish validated page-cache measurements; never execute new queries."""

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def storage_read_table(rows, datasets, layouts):
    """Report OS-attributed reads; never substitute zero for missing counters."""
    indexed = {}
    for row in rows:
        key = (row["dataset_id"], row["layout_id"], row["cache_mode"])
        if key in indexed:
            raise ValueError(f"duplicate cache summary cell: {key}")
        indexed[key] = row

    def kib(row, field):
        value = row.get(field, "")
        if field == "mean_os_read_bytes" and (
            not value
            or int(row["os_read_bytes_available_rows"]) != int(row["measured_rows"])
        ):
            return "--"
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"invalid byte summary: {field}")
        return f"{number / 1024:.2f}"

    lines = [
        r"\begin{tabular}{llrrr}",
        r"Dataset & Layout & Logical (KiB) & Cold reads (KiB) & Warm reads (KiB) \\",
        r"\hline",
    ]
    names = {
        "stanford_bunny": "Bunny", "stanford_armadillo": "Armadillo",
        "stanford_dragon": "Dragon", "usgs_cameron_peak": "Cameron Peak",
        "noaa_santiam_river": "Santiam River", "noaa_long_island": "Long Island",
        "noaa_southwest_florida": "Southwest Florida",
        "A3_isotropic_hilbert": "Isotropic Hilbert", "A6_rch_C3": "RCH/C3",
    }
    for dataset in datasets:
        for layout in layouts:
            cold = indexed[dataset, layout, "cold_page_cache"]
            warm = indexed[dataset, layout, "warm_page_cache"]
            if float(cold["mean_logical_bytes"]) != float(warm["mean_logical_bytes"]):
                raise ValueError("cache modes have different logical query workloads")
            values = (
                kib(cold, "mean_logical_bytes"),
                kib(cold, "mean_os_read_bytes"),
                kib(warm, "mean_os_read_bytes"),
            )
            lines.append(
                names.get(dataset, dataset.replace("_", r"\_"))
                + " & "
                + names.get(layout, layout.replace("_", r"\_"))
                + " & "
                + " & ".join(values)
                + r" \\"
            )
    return "\n".join(lines + [r"\end{tabular}"]) + "\n"


def publish_storage_io(source, generated):
    """Validate frozen results and publish I/O only; never access measured binaries."""
    sys.path.insert(0, str(ROOT))
    from experiments.runners.run_application_cache import validate_metrics

    manifest_path = source / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    identity = manifest["identity"]
    if manifest["status"] != "completed":
        raise ValueError("cache measurements are incomplete")
    snapshot = source / "application_source_manifest.json"
    if digest(snapshot) != identity["application_manifest_sha256"]:
        raise ValueError("frozen application snapshot checksum mismatch")
    application = json.loads(snapshot.read_text())
    selected_datasets = [d for d in application["datasets"] if d["dataset_id"] in identity["datasets"]]
    expected = {d["dataset_id"] + "__" + layout
                for d in selected_datasets for layout in d["layout_schedule"]}
    if set(manifest["tasks"]) != expected or len(selected_datasets) != len(identity["datasets"]):
        raise ValueError("cache task/dataset coverage mismatch")
    summary_path = source / "summary.csv"
    if digest(summary_path) != manifest["summary_sha256"]:
        raise ValueError("cache summary checksum mismatch")
    with summary_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    cells = {(r["dataset_id"] + "__" + r["layout_id"], r["cache_mode"]): r for r in rows}
    if len(cells) != len(rows) or set(cells) != {(k, mode) for k in expected for mode in identity["modes"]}:
        raise ValueError("cache summary coverage mismatch")
    checksums = {"run_manifest.json": digest(manifest_path),
                 snapshot.name: digest(snapshot), summary_path.name: digest(summary_path)}
    frozen_workloads = {}
    for dataset in selected_datasets:
        data = {}
        for name in ("query_windows.csv", "query_results.csv"):
            record = dataset["query_results"][name]
            path = ROOT / record["path"]
            path.resolve().relative_to(ROOT)
            if digest(path) != record["sha256"]:
                raise ValueError(f"frozen workload checksum mismatch: {path}")
            with path.open(newline="") as stream:
                data[name] = list(csv.DictReader(stream))
            checksums[str(path.relative_to(ROOT))] = record["sha256"]
        frozen_workloads[dataset["dataset_id"]] = data
    for key, item in manifest["tasks"].items():
        metrics = source / item["metrics"]
        oracle = source / (key + ".oracle.tsv")
        for path, checksum in ((metrics, item["metrics_sha256"]),):
            path.resolve().relative_to(source.resolve())
            if digest(path) != checksum:
                raise ValueError(f"frozen cache file checksum mismatch: {path}")
            checksums[str(path.relative_to(source))] = checksum
        if item["status"] != "passed":
            raise ValueError("cache task did not pass")
        text = oracle.read_text()
        dataset_id, layout = key.split("__", 1)
        dataset = next(d for d in selected_datasets if d["dataset_id"] == dataset_id)
        if (item["oracle_sha256"] != dataset["query_results"]["query_results.csv"]["sha256"]
                or item["query_sha256"] != dataset["query_results"]["query_windows.csv"]["sha256"]):
            raise ValueError("cache task refers to a different frozen workload")
        workload = frozen_workloads[dataset_id]
        references = [r for r in workload["query_results.csv"] if r["layout_id"] == layout]
        expected_results = {r["query_id"]: r for r in references}
        queries = workload["query_windows.csv"]
        if len(references) != len(expected_results) or len(references) != len(queries):
            raise ValueError("frozen result coverage mismatch")
        lines = []
        for query in queries:
            reference = expected_results[query["query_id"]]
            if reference["oracle_match"] != "true":
                raise ValueError("frozen reference did not match oracle")
            fields = [query[k] for k in ("query_id", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z")]
            lines.append("\t".join(fields + [reference["result_count"], reference["result_ids_sha256"]]))
        if text != "\n".join(lines) + "\n":
            raise ValueError("cached oracle TSV differs from frozen query/results")
        checksums[oracle.name] = digest(oracle)
        query_ids = [line.split("\t")[0] for line in text.splitlines()]
        if len(set(query_ids)) != len(query_ids) or len(query_ids) != application["query_count_per_dataset_layout"]:
            raise ValueError("frozen oracle query coverage mismatch")
        raw = validate_metrics(metrics, {"oracle_tsv": text, "query_ids": query_ids}, identity["repeats"])
        for mode in identity["modes"]:
            measured = [r for r in raw if r["cache_mode"] == mode]
            cell = cells[key, mode]
            available = [int(r["os_read_bytes"]) for r in measured if r["os_read_bytes"]]
            if int(cell["measured_rows"]) != len(measured) or int(cell["os_read_bytes_available_rows"]) != len(available):
                raise ValueError("cache I/O sample count mismatch")
            for field, values in (("mean_logical_bytes", [int(r["logical_bytes"]) for r in measured]),
                                  ("mean_os_read_bytes", available)):
                if len(values) == len(measured):
                    if not math.isclose(float(cell[field]), sum(values) / len(values), rel_tol=1e-12, abs_tol=1e-8):
                        raise ValueError("cache I/O mean differs from measured rows")
                elif cell[field] != "":
                    raise ValueError("incomplete I/O counter must not have a mean")
    table = generated / "tables/table_application_cache_io.tex"
    evidence = generated / "outputs/application_cache/io_evidence.md"
    for path in (table, evidence):
        path.parent.mkdir(parents=True, exist_ok=True)
    layouts = [layout for layout in ("A3_isotropic_hilbert", "A6_rch_C3")
               if all(dataset + "__" + layout in expected for dataset in identity["datasets"])]
    if not layouts:
        raise ValueError("I/O table requires an isotropic Hilbert or RCH/C3 reference")
    table.write_text(storage_read_table(rows, identity["datasets"], layouts))
    evidence.write_text(
        "# Storage-read measurements\n\nFrozen-result validation only; no queries or measured binaries executed.\n"
        "Arithmetic mean KiB per query execution over all queries and repeats; 1 KiB = 1024 bytes.\n"
        "Linux /proc/self/io read_bytes differences cover page-file open/header/query/close.\n"
        "Cache setup and resident directory are excluded; device caches are uncontrolled.\n"
        "Counters are process-attributed storage reads, not device-controller telemetry.\n"
        "Read-ahead can exceed logical bytes; missing/incomplete counters are --, never zero.\n"
    )
    proof = {
        "validation": "frozen metrics, oracle, cache residency and I/O arithmetic; no executable replay",
        "source_manifest_sha256": digest(manifest_path), "generator_sha256": digest(Path(__file__)),
        "measured_identity": identity, "frozen_files_sha256": checksums,
        "artifacts_sha256": {str(p.relative_to(generated)): digest(p) for p in (table, evidence)},
    }
    (evidence.parent / "io_analysis_manifest.json").write_text(json.dumps(proof, indent=2) + "\n")
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument(
        "--artifact-root", type=Path, default=ROOT / "analysis/generated"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--io-only", action="store_true", help="validate frozen metrics and publish storage I/O without measured binaries")
    args = parser.parse_args()
    source = args.input_root.resolve()
    if args.io_only:
        if args.validate_only:
            parser.error("--io-only and --validate-only cannot be combined")
        publish_storage_io(source, args.artifact_root.resolve())
        print("Validated frozen cache measurements and published storage I/O; no queries executed")
        return
    manifest = json.loads((source / "run_manifest.json").read_text())
    identity = manifest["identity"]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "experiments/runners/run_application_cache.py"),
            "--application-root",
            identity["application_root"],
            "--probe-bin",
            identity["binary"],
            "--repeats",
            str(identity["repeats"]),
            "--seed",
            str(identity["seed"]),
            "--output-dir",
            str(source),
            "--validate-only",
            *[
                arg
                for dataset in identity["datasets"]
                for arg in ("--dataset", dataset)
            ],
        ],
        check=True,
    )
    generated = args.artifact_root.resolve()
    output = generated / "outputs/application_cache"
    proof_path = output / "analysis_manifest.json"
    if args.validate_only:
        proof = json.loads(proof_path.read_text())
        if proof["source_manifest_sha256"] != digest(
            source / "run_manifest.json"
        ) or proof["generator_sha256"] != digest(Path(__file__)):
            raise ValueError("cache source or artifact generator changed")
        for name, checksum in proof["artifacts_sha256"].items():
            path = (generated / name).resolve()
            path.relative_to(generated)
            if digest(path) != checksum:
                raise ValueError("cache artifact checksum mismatch: " + name)
        print(
            json.dumps(
                {"status": "passed", "artifacts": len(proof["artifacts_sha256"])}
            )
        )
        return
    for directory in [output, generated / "figures", generated / "tables"]:
        directory.mkdir(parents=True, exist_ok=True)
    for src, dest in [
        ("summary.csv", "summary.csv"),
        ("run_manifest.json", "source_manifest.json"),
    ]:
        shutil.copyfile(source / src, output / dest)
    with (source / "summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    datasets = identity["datasets"]
    layouts = list(dict.fromkeys(row["layout_id"] for row in rows))
    indexed = {(r["dataset_id"], r["layout_id"], r["cache_mode"]): r for r in rows}
    fig, axes = plt.subplots(
        1, 2, figsize=(13, max(4, len(datasets) * 0.85)), sharey=True
    )
    for ax, mode in zip(axes, identity["modes"]):
        for number, layout in enumerate(layouts):
            values = [
                float(indexed[d, layout, mode]["mean_query_median_seconds"]) * 1000
                for d in datasets
            ]
            offset = (number - (len(layouts) - 1) / 2) * 0.8 / len(layouts)
            ax.barh(
                [i + offset for i in range(len(datasets))],
                values,
                height=0.8 / len(layouts),
                label=layout,
            )
        ax.set_xscale("log")
        ax.set_xlabel("Mean of per-query median times (ms; log scale)")
        ax.set_title(mode.replace("_", " "))
        ax.set_yticks(range(len(datasets)), datasets)
    fig.legend(
        *axes[0].get_legend_handles_labels(), loc="lower center", ncol=4, fontsize=8
    )
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    figure = generated / "figures/fig_application_cache_latency.pdf"
    fig.savefig(figure)
    plt.close(fig)
    table = generated / "tables/table_application_cache.tex"
    selected = [
        layout for layout in ["A3_isotropic_hilbert", "A6_rch_C3"] if layout in layouts
    ] or layouts
    lines = [
        r"\begin{tabular}{llrr}",
        r"Dataset & Layout & Cold (ms) & Warm (ms) \\",
        r"\hline",
    ]
    for dataset in datasets:
        for layout in selected:
            values = [
                float(indexed[dataset, layout, mode]["mean_query_median_seconds"])
                * 1000
                for mode in identity["modes"]
            ]
            lines.append(
                dataset.replace("_", r"\_")
                + " & "
                + layout.replace("_", r"\_")
                + f" & {values[0]:.4f} & {values[1]:.4f}"
                + r" \\"
            )
    table.write_text("\n".join(lines + [r"\end{tabular}"]) + "\n")
    io_table = publish_storage_io(source, generated)
    (output / "evidence.md").write_text(
        "# File page-cache measurements\n\nVerified cold/warm file-page residency; device-controller caches are not controlled.\nDirectory resident; timing includes open/header/query/close. Values are means of\nper-query median times across repeats, without population confidence intervals.\n"
    )
    with (output / "evidence.md").open("a") as stream:
        stream.write(
            "\nThe I/O table reports arithmetic mean bytes per measured query execution "
            "across all queries and repeats (KiB = 1024 bytes). Logical bytes count "
            "page reads. Storage reads are process-attributed Linux /proc/self/io "
            "read_bytes deltas around open/header/query/close, not device-controller "
            "telemetry. Cache preparation and the resident directory are excluded. "
            "Missing or incomplete OS counters are shown as --, never zero. "
            "Cold reads may include filesystem read-ahead; warm reads may be zero.\n"
        )
    files = [
        figure,
        table,
        io_table,
        output / "io_evidence.md",
        output / "io_analysis_manifest.json",
        *[output / n for n in ["summary.csv", "source_manifest.json", "evidence.md"]],
    ]
    proof = {
        "source_manifest_sha256": digest(source / "run_manifest.json"),
        "generator_sha256": digest(Path(__file__)),
        "artifacts_sha256": {str(p.relative_to(generated)): digest(p) for p in files},
    }
    proof_path.write_text(json.dumps(proof, indent=2) + "\n")


if __name__ == "__main__":
    main()
