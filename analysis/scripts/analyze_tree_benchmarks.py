#!/usr/bin/env python3
"""Validate a complete tree benchmark and produce scope-separated paired artifacts."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
from experiments.application_layouts import APPLICATION_OUTPUT_ROOT

BACKENDS = ("cgal_kdtree", "kdtree_dfs_pages", "input_pages", "hilbert_pages", "rch_pages",
            "ram_full_scan", "hilbert_ram_pages", "rch_ram_pages")
PAGE_BACKENDS = ("kdtree_dfs_pages", "input_pages", "hilbert_pages", "rch_pages")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate(root: Path) -> tuple[dict, dict]:
    state = json.loads((root / "run_manifest.json").read_text())
    if state["schema"] != "rch.tree_benchmark.v1" or tuple(state["backends"]) != BACKENDS:
        raise ValueError("tree protocol/backend mismatch")
    if state["process_blocks"] < 1 or not state["datasets"]:
        raise ValueError("empty protocol")
    if digest(root / "source_manifest.json") != state["source_manifest_sha256"]:
        raise ValueError("source snapshot mismatch")
    repository = Path(__file__).resolve().parents[2]
    for source_path, checksum in state.get("source_sha256", {}).items():
        target = (repository / source_path).resolve()
        target.relative_to(repository)
        if digest(target) != checksum:
            raise ValueError(f"benchmark source changed: {source_path}; rerun the benchmark")
    inventory = state["files_sha256"]
    for relative, checksum in inventory.items():
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        if digest(path) != checksum:
            raise ValueError(f"checksum mismatch: {relative}")
    groups = {}
    datasets = state["datasets"]
    if len({d["dataset_id"] for d in datasets}) != len(datasets):
        raise ValueError("duplicate dataset")
    for dataset in datasets:
        id_ = dataset["dataset_id"]
        expected_queries = set(dataset["query_ids"])
        if not expected_queries or len(expected_queries) != len(dataset["query_ids"]):
            raise ValueError("invalid query inventory")
        parity = {}
        for backend in BACKENDS:
            rows = []
            preps = []
            order_checksum = None
            for block in range(state["process_blocks"]):
                prefix = Path(id_) / f"block_{block}" / backend
                for name in ("query_metrics.csv", "preparation.csv"):
                    if str(prefix / name) not in inventory:
                        raise ValueError("required file absent from checksum inventory")
                current = read_csv(root / prefix / "query_metrics.csv")
                if len(current) != len(expected_queries) or {r["query_id"] for r in current} != expected_queries:
                    raise ValueError("missing/duplicate query rows")
                prep = read_csv(root / prefix / "preparation.csv")
                if len(prep) != 1 or prep[0]["backend"] != backend or int(prep[0]["point_count"]) != dataset["point_count"] or int(prep[0]["bucket"]) != state["bucket_size"]:
                    raise ValueError("invalid preparation record")
                preps += prep
                for r in current:
                    expected_scope = "warm_page_file" if backend in PAGE_BACKENDS else "resident_memory"
                    if r["backend"] != backend or r["scope"] != expected_scope or r["repeat"] != "1" or r["oracle_match"] != "true":
                        raise ValueError("invalid backend, scope, repeat or oracle result")
                    for name in ("wall_seconds", "cpu_seconds"):
                        value = float(r[name])
                        if not math.isfinite(value) or value < 0:
                            raise ValueError("invalid timing")
                    count = int(r["result_count"])
                    if not 0 <= count <= dataset["point_count"] or len(r["result_hash"]) != 64:
                        raise ValueError("invalid query result")
                    if backend in PAGE_BACKENDS:
                        for name in ("points.page", "points.index", "order.csv"):
                            if str(prefix / name) not in inventory:
                                raise ValueError("missing layout file checksum")
                    signature = r["result_count"], r["result_hash"]
                    if parity.setdefault(r["query_id"], signature) != signature:
                        raise ValueError("cross-backend/block result mismatch")
                    r["block"] = block
                    rows.append(r)
                if backend in PAGE_BACKENDS:
                    current_order_checksum = inventory[str(prefix / "order.csv")]
                    if order_checksum is not None and current_order_checksum != order_checksum:
                        raise ValueError("layout ordering changed across process blocks")
                    order_checksum = current_order_checksum
            groups[id_, backend] = rows, preps
    return state, groups


def analyze(root: Path, output: Path, artifact_root: Path | None = None) -> None:
    state, groups = validate(root)
    summaries = []
    paired = []
    for (id_, backend), (rows, preps) in groups.items():
        values = [float(r["wall_seconds"]) for r in rows]
        prefix = root / id_ / "block_0" / backend
        summary = {"dataset_id": id_, "backend": backend, "scope": rows[0]["scope"], "rows": len(rows),
                   "mean_wall_seconds": statistics.fmean(values), "p50_wall_seconds": float(np.quantile(values, .5)),
                   "p95_wall_seconds": float(np.quantile(values, .95)), "p99_wall_seconds": float(np.quantile(values, .99)),
                   "mean_cpu_seconds": statistics.fmean(float(r["cpu_seconds"]) for r in rows),
                   "backend_prepare_median_seconds": statistics.median(float(p["prepare_seconds"]) for p in preps),
                   "tree_build_median_seconds": statistics.median(float(p["tree_build_seconds"]) for p in preps),
                   "process_peak_rss_kib": max(int(r["peak_rss_kib"]) for r in rows),
                   "data_file_bytes": (prefix / "points.page").stat().st_size if backend in PAGE_BACKENDS else None,
                   "index_file_bytes": (prefix / "points.index").stat().st_size if backend in PAGE_BACKENDS else None}
        for name in ("candidate_pages", "pages_read", "records_examined"):
            summary["mean_" + name] = statistics.fmean(float(r[name]) for r in rows) if all(r[name] for r in rows) else None
        summaries.append(summary)
    ids = [d["dataset_id"] for d in state["datasets"]]
    rng = np.random.default_rng(20261105)
    for id_ in ids:
        for tree, references in (("kdtree_dfs_pages", ("input_pages", "hilbert_pages", "rch_pages")),
                                 ("cgal_kdtree", ("ram_full_scan", "hilbert_ram_pages", "rch_ram_pages"))):
            for reference in references:
                tree_rows = groups[id_, tree][0]
                ref = {(r["query_id"], r["block"]): float(r["wall_seconds"]) for r in groups[id_, reference][0]}
                deltas = defaultdict(list)
                for r in tree_rows:
                    deltas[r["query_id"]].append(float(r["wall_seconds"]) - ref[r["query_id"], r["block"]])
                values = np.array([statistics.fmean(v) for _, v in sorted(deltas.items())])
                means = np.mean(rng.choice(values, size=(10000, len(values))), axis=1)
                paired.append({"dataset_id": id_, "backend": tree, "reference": reference,
                               "scope": tree_rows[0]["scope"], "query_count": len(values),
                               "mean_delta_seconds": float(np.mean(values)), "ci95_low_seconds": float(np.quantile(means, .025)),
                               "ci95_high_seconds": float(np.quantile(means, .975)),
                               "inference_scope": "descriptive within-dataset query bootstrap; repeated processes averaged; unadjusted intervals"})
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "summary.csv", summaries)
    write_csv(output / "paired_comparisons.csv", paired)
    (output / "evidence.md").write_text(
        "# Tree benchmark evidence\n\nAll queries match the original-ID brute-force oracle and agree across backends and blocks.\n\n"
        "Warm page-file DFS-layout effects and resident-memory native-tree effects are reported in separate groups. "
        "IDs are materialized and sorted inside query timing; hashing and oracle checks are outside. "
        "Counters unavailable from CGAL are null, not zero. RSS is process cumulative, including data and oracle. "
        "Preparation excludes input load and earlier SFC ordering; source ordering times remain in the run manifest. "
        "These measurements do not establish complete preparation amortization, physical cold-disk I/O, or DBMS performance. "
        "CGAL point/node allocation size is not measured. Intervals describe queries on each fixed dataset, not new independent scenes.\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    for axis, scope in zip(axes, ("warm_page_file", "resident_memory")):
        backends = [b for b in BACKENDS if (b in PAGE_BACKENDS) == (scope == "warm_page_file")]
        x = np.arange(len(ids))
        for j, backend in enumerate(backends):
            values = [next(r["mean_wall_seconds"] for r in summaries if r["dataset_id"] == id_ and r["backend"] == backend) for id_ in ids]
            axis.bar(x + (j - 1.5) * .2, np.array(values) * 1000, width=.19, label=backend)
        axis.set_xticks(x, ids, rotation=25, ha="right")
        axis.set_ylabel("Mean query wall time (ms)")
        axis.set_title(scope)
        axis.legend(fontsize=6)
    fig.savefig(output / "fig_tree_query_latency.pdf")
    plt.close(fig)
    lines = [r"\begin{tabular}{llr}", r"Dataset / scope & Backend & Mean query (ms) \\", r"\hline"]
    for row in summaries:
        label = (row["dataset_id"] + " / " + row["scope"]).replace("_", r"\_")
        backend = row["backend"].replace("_", r"\_")
        lines.append(f"{label} & {backend} & {row['mean_wall_seconds'] * 1000:.4f}" + r" \\")
    lines.append(r"\end{tabular}")
    (output / "table_tree_query.tex").write_text("\n".join(lines) + "\n")
    if artifact_root is not None:
        import shutil
        for subdir, name in (("figures", "fig_tree_query_latency.pdf"), ("tables", "table_tree_query.tex")):
            (artifact_root / subdir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output / name, artifact_root / subdir / name)
    published = {str(Path(subdir) / name): digest(artifact_root / subdir / name)
                 for subdir, name in (("figures", "fig_tree_query_latency.pdf"), ("tables", "table_tree_query.tex"))} if artifact_root else {}
    files = [p for p in output.iterdir() if p.is_file() and p.name != "analysis_manifest.json"]
    (output / "analysis_manifest.json").write_text(json.dumps({"status": "validated_tree_matrix", "source_manifest_sha256": digest(root / "run_manifest.json"),
        "artifacts": {p.name: digest(p) for p in files}, "published_artifacts": published}, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--artifact-root", type=Path)
    p.add_argument("--application-root", type=Path, default=REPOSITORY_ROOT / APPLICATION_OUTPUT_ROOT, help="reject stale results from another application run")
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args()
    if a.application_root is not None:
        tree = json.loads((a.input_root / "run_manifest.json").read_text())
        if tree["source_manifest_sha256"] != digest(a.application_root / "run_manifest.json"):
            raise ValueError("tree benchmark belongs to a different application run")
    if a.validate_only:
        validate(a.input_root)
        if a.output_dir:
            state = json.loads((a.output_dir / "analysis_manifest.json").read_text())
            if state["source_manifest_sha256"] != digest(a.input_root / "run_manifest.json"):
                raise ValueError("stale tree analysis")
            for name, sha in state["artifacts"].items():
                if digest(a.output_dir / name) != sha:
                    raise ValueError("stale tree artifact")
            if a.artifact_root:
                for name, sha in state["published_artifacts"].items():
                    if digest(a.artifact_root / name) != sha:
                        raise ValueError("stale published tree artifact")
        print("tree inventory, matrix and oracle parity verified")
    else:
        analyze(a.input_root, a.output_dir or a.input_root / "analysis", a.artifact_root)


if __name__ == "__main__":
    main()
