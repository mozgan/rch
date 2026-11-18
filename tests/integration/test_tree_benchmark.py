#!/usr/bin/env python3
"""Exact range-query parity, duplicate IDs and permutation checks for the CGAL adapter."""
import csv
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

BACKENDS = ("cgal_kdtree", "kdtree_dfs_pages", "input_pages", "hilbert_pages", "rch_pages",
            "ram_full_scan", "hilbert_ram_pages", "rch_ram_pages")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_layouts import LAYOUTS, RULES


def smoke(binary: Path) -> None:
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rch_tree_correctness_", dir=ROOT / "build") as directory:
        root = Path(directory)
        for name, points in {
            "grid_duplicates": [(float(i % 7), float((i // 7) % 7), float(i // 49)) for i in range(300)] + [(0., 0., 0.)] * 10,
            "coplanar": [(float(i), float(i % 3), 0.) for i in range(140)],
            "identical": [(1e9, -1e9, 3.)] * 140,
            "singleton": [(0., 0., 0.)],
        }.items():
            fixture = root / name
            fixture.mkdir()
            xyz = fixture / "points.csv"
            xyz.write_text("".join(",".join(map(str, p)) + "\n" for p in points))
            lo = tuple(min(p[k] for p in points) for k in range(3))
            hi = tuple(max(p[k] for p in points) for k in range(3))
            boxes = {"all": (lo, hi), "point": (points[0], points[0]),
                     "empty": ((2e10, 2e10, 2e10), (2e10 + 1, 2e10 + 1, 2e10 + 1)),
                     "boundary": (lo, tuple((lo[k] + hi[k]) / 2 for k in range(3)))}
            queries = fixture / "queries.csv"
            queries.write_text("query_id,min_x,min_y,min_z,max_x,max_y,max_z\n" + "".join(
                key + "," + ",".join(map(str, (*a, *b))) + "\n" for key, (a, b) in boxes.items()))
            order = fixture / "reverse.csv"
            order.write_text("rank,raw_index,key\n" + "".join(f"{rank},{id_},0\n" for rank, id_ in enumerate(reversed(range(len(points))))))
            for backend in BACKENDS:
                output = fixture / backend
                command = [str(binary), "--points", str(xyz), "--queries", str(queries),
                           "--backend", backend, "--output", str(output), "--repeats", "2", "--bucket", "32"]
                if backend.startswith(("hilbert", "rch")):
                    command += ["--order", str(order)]
                subprocess.run(command, check=True, capture_output=True, text=True)
                rows = list(csv.DictReader((output / "query_metrics.csv").open()))
                assert len(rows) == 8
                for row in rows:
                    a, b = boxes[row["query_id"]]
                    ids = [i for i, p in enumerate(points) if all(a[k] <= p[k] <= b[k] for k in range(3))]
                    digest = hashlib.sha256(b"".join(struct.pack("<Q", i) for i in ids)).hexdigest()
                    assert row["result_hash"] == digest, (name, backend, row)
                    assert int(row["result_count"]) == len(ids) and row["oracle_match"] == "true"
                if (output / "order.csv").exists():
                    ids = [int(r["raw_index"]) for r in csv.DictReader((output / "order.csv").open())]
                    assert sorted(ids) == list(range(len(points)))
                # Existing output must fail, rather than silently overwrite evidence.
                assert subprocess.run(command, capture_output=True).returncode != 0
            bad = fixture / "bad_queries.csv"
            bad.write_text("query_id,min_x,min_y,min_z,max_x,max_y,max_z\nbad,1,0,0,-1,0,0\n")
            assert subprocess.run([str(binary), "--points", str(xyz), "--queries", str(bad),
                                   "--backend", "cgal_kdtree", "--output", str(fixture / "invalid")], capture_output=True).returncode != 0
            if name == "grid_duplicates":
                pipeline_fixture(fixture, xyz, queries, order, len(points), binary)
        print(json.dumps({"status": "passed", "fixtures": 4, "backends": len(BACKENDS), "oracle_checked_rows": 256}))


def pipeline_fixture(root: Path, xyz: Path, queries: Path, order: Path, count: int, binary: Path) -> None:
    """Exercise runner -> native processes -> paired analysis, plus invalid matrix rejection."""
    sys.path.insert(0, str(ROOT / "analysis/scripts"))
    from analyze_tree_benchmarks import digest, validate
    source = root / "source"
    source.mkdir()
    order_record = {"path": str(order.relative_to(ROOT)), "sha256": digest(order)}
    dataset = {"dataset_id": "fixture", "point_count": count,
               "input_csv": str(xyz.relative_to(ROOT)), "input_csv_sha256": digest(xyz),
               "query_workload": {"file": str(queries.relative_to(ROOT)), "file_sha256": digest(queries)},
               "order_files": {"A3_isotropic_hilbert": order_record, "A6_rch": order_record},
               "ordering_wall_seconds": {"A3_isotropic_hilbert": 0, "A6_rch": 0}}
    (source / "run_manifest.json").write_text(json.dumps({"schema": "rch.application_query",
        "protocol": "application_window_query", "ordering": {"layouts": list(LAYOUTS), "layout_rules": RULES}, "query_count_per_dataset_layout": 4,
        "expected_dataset_ids": ["fixture"], "datasets": [dataset]}))
    output = root / "pipeline"
    subprocess.run([sys.executable, str(ROOT / "experiments/runners/run_tree_benchmarks.py"),
        "--source-root", str(source), "--output-dir", str(output), "--binary", str(binary),
        "--repeats", "2", "--bucket", "32"], check=True, capture_output=True, text=True)
    validate(output)
    assert (output / "analysis/fig_tree_query_latency.pdf").is_file()
    assert len(list(csv.DictReader((output / "analysis/paired_comparisons.csv").open()))) == 6
    published = root / "published"
    analyzer = [sys.executable, str(ROOT / "analysis/scripts/analyze_tree_benchmarks.py"),
                "--input-root", str(output), "--output-dir", str(published / "outputs"),
                "--artifact-root", str(published), "--application-root", str(source)]
    subprocess.run(analyzer, check=True, capture_output=True, text=True)
    subprocess.run(analyzer + ["--validate-only"], check=True, capture_output=True, text=True)
    other_source = root / "other_application"; other_source.mkdir()
    (other_source / "run_manifest.json").write_text("{}")
    rejected = subprocess.run(analyzer[:-1] + [str(other_source), "--validate-only"], capture_output=True, text=True)
    assert rejected.returncode != 0 and "application run" in rejected.stderr
    manifest_path = output / "run_manifest.json"
    original_manifest = manifest_path.read_text()
    changed = json.loads(original_manifest)
    changed["source_sha256"]["experiments/runners/run_tree_benchmarks.py"] = "0" * 64
    manifest_path.write_text(json.dumps(changed))
    try:
        validate(output)
    except ValueError as exc:
        assert "benchmark source changed" in str(exc)
    else:
        raise AssertionError("changed benchmark source accepted")
    finally:
        manifest_path.write_text(original_manifest)
    with (published / "tables/table_tree_query.tex").open("a") as stream:
        stream.write("corrupt artifact\n")
    assert subprocess.run(analyzer + ["--validate-only"], capture_output=True).returncode != 0
    manifest = output / "run_manifest.json"
    state = json.loads(manifest.read_text())
    metric = output / "fixture/block_0/cgal_kdtree/query_metrics.csv"
    lines = metric.read_text().splitlines(keepends=True)
    metric.write_text("".join(lines[:-1]))
    # Refresh the digest to make sure row completeness, not only checksum, is tested.
    state["files_sha256"][str(metric.relative_to(output))] = digest(metric)
    manifest.write_text(json.dumps(state))
    try:
        validate(output)
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete matrix accepted")


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())
