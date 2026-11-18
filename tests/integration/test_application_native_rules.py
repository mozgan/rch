#!/usr/bin/env python3
"""Real executables on synthetic points: seven layouts, exact queries and application artifacts.

Only dataset loading is replaced with a local synthetic provenance fixture;
ordering, page storage, queries, compression, statistics and plots are real.
"""

from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_layouts import LAYOUTS, NATIVE_LAYOUTS, RULES
from experiments.runners import run_application_query_smoke as runner
from analysis.scripts import analyze_application_query_metrics as analysis
from analysis.scripts import make_application_artifacts as artifacts
from data.synthetic.generators.gaussian_ellipsoid import ellipsoid_points


def main():
    p = argparse.ArgumentParser()
    p.add_argument("order_binary", type=Path)
    p.add_argument("query_binary", type=Path)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="application_native_", dir=ROOT / "build"
    ) as directory:
        work = Path(directory)
        blob = work / "fixture.source"
        blob.write_text("synthetic test provenance; not a real acquisition\n")
        relative = str(blob.relative_to(ROOT))
        checksum = runner.sha256_file(blob)
        points = ellipsoid_points(384, (6.0, 2.0, 1.0), 2026)
        provenance = dict(
            dataset_id="fixture",
            point_count=len(points),
            points=points,
            source_manifest=relative,
            source_manifest_sha256=checksum,
        )
        for name in ("archive", "processed_file", "preprocessing_manifest"):
            provenance[name] = relative
        for name in (
            "archive_sha256",
            "processed_sha256",
            "preprocessing_manifest_sha256",
        ):
            provenance[name] = checksum
        args = SimpleNamespace(
            ordering_repeats=5,
            measured_repeats=5,
            full_query_matrix=True,
            measure_warm_cache_compression=True,
            dataset=["fixture"],
            output_dir=work / "run",
            raw_dir=work,
            processed_dir=work,
            manifest=blob,
            rch_order_bin=a.order_binary.resolve(),
            smoke_bin=a.query_binary.resolve(),
        )
        with (
            patch.object(runner, "parse_args", return_value=args),
            patch.object(
                runner,
                "load_dataset_provenance",
                return_value=copy.deepcopy(provenance),
            ),
        ):
            assert runner.main() == 0
        manifest_path = args.output_dir / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        d = manifest["datasets"][0]
        assert set(manifest["ordering"]["layouts"]) == set(LAYOUTS)
        assert len(d["layout_schedule"]) == 7
        metrics = list(
            csv.DictReader((ROOT / d["warm_cache_query_metrics"]["path"]).open())
        )
        assert len(metrics) == 8960 and {r["layout_id"] for r in metrics} == set(
            LAYOUTS
        )
        for layout in NATIVE_LAYOUTS:
            assert (
                d["ordering_diagnostics"][layout]["bit_allocator"]
                == RULES[layout]["bit_allocator"]
            )
        # Independent NumPy inclusive-box oracle for all 1,792 correctness rows.
        windows = list(
            csv.DictReader(
                (ROOT / d["query_results"]["query_windows.csv"]["path"]).open()
            )
        )
        xyz = np.asarray(points)
        reference = {}
        for row in windows:
            lo = np.array([float(row["min_" + axis]) for axis in "xyz"])
            hi = np.array([float(row["max_" + axis]) for axis in "xyz"])
            ids = np.flatnonzero(np.all((xyz >= lo) & (xyz <= hi), axis=1))
            reference[row["query_id"]] = (
                len(ids),
                hashlib.sha256(
                    b"".join(struct.pack("<Q", int(i)) for i in ids)
                ).hexdigest(),
            )
        correctness = list(
            csv.DictReader(
                (ROOT / d["query_results"]["query_results.csv"]["path"]).open()
            )
        )
        for row in correctness:
            assert (int(row["result_count"]), row["result_ids_sha256"]) == reference[
                row["query_id"]
            ]
        # Run actual 10,000-draw query bootstrap and the publication renderer.
        original = artifacts.analyze

        def fixture_analyze(source, output, **kwargs):
            return original(source, output, expected_datasets=("fixture",), **kwargs)

        from matplotlib.axes import Axes

        heights = []
        real_bar = Axes.bar

        def record_bar(axis, x, height, *args, **kwargs):
            heights.append(list(height))
            return real_bar(axis, x, height, *args, **kwargs)

        with (
            patch.object(artifacts, "analyze", side_effect=fixture_analyze),
            patch.object(Axes, "bar", record_bar),
        ):
            artifacts.generate(args.output_dir, work / "artifacts")
        snapshot = work / "artifacts/outputs/application_query"
        summary = list(csv.DictReader((snapshot / "summary.csv").open()))
        assert {r["layout_id"] for r in summary} == set(LAYOUTS)
        assert len(heights) == 1
        np.testing.assert_allclose(
            heights[0], [float(r["p50_wall_seconds"]) * 1000 for r in summary]
        )
        pairs = list(csv.DictReader((snapshot / "paired_comparisons.csv").open()))
        assert len(pairs) == 19
        for layout in NATIVE_LAYOUTS:
            assert any(
                r["layout_id"] == layout and r["reference"] == "A3_isotropic_hilbert"
                for r in pairs
            )
            assert any(
                r["layout_id"] == layout and r["reference"] == "A6_rch" for r in pairs
            )
        tex = (work / "artifacts/tables/table_application_query.tex").read_text()
        assert all(layout.replace("_", r"\_") in tex for layout in NATIVE_LAYOUTS)
        assert (
            len(
                list(csv.DictReader((snapshot / "quantization_diagnostics.csv").open()))
            )
            == 7
        )
        checker = [
            sys.executable,
            str(ROOT / "analysis/scripts/check_application_artifacts.py"),
            "--input-root",
            str(args.output_dir),
            "--output-root",
            str(work / "artifacts"),
        ]
        subprocess.run(checker, check=True, capture_output=True)
        published = work / "artifacts/tables/table_application_query.tex"
        published.write_text(published.read_text() + "changed\n")
        assert subprocess.run(checker, capture_output=True).returncode != 0
        # Incomplete native measurements are rejected even after refreshing SHA metadata.
        metric_path = ROOT / d["warm_cache_query_metrics"]["path"]
        saved_metrics = metric_path.read_bytes()
        saved_manifest = manifest_path.read_bytes()
        changed = metrics[:-1]
        with metric_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(changed[0]))
            writer.writeheader()
            writer.writerows(changed)
        d["warm_cache_query_metrics"]["sha256"] = runner.sha256_file(metric_path)
        manifest_path.write_text(json.dumps(manifest))
        try:
            analysis.analyze(
                args.output_dir, work / "incomplete", expected_datasets=("fixture",)
            )
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete native query matrix accepted")
        metric_path.write_bytes(saved_metrics)
        manifest_path.write_bytes(saved_manifest)
        manifest = json.loads(saved_manifest)
        d = manifest["datasets"][0]
        # Incorrect rule cannot hide behind renewed file checksum and copied diagnostics.
        layout = "A6_rch_C3"
        record = d["order_files"][layout]
        path = ROOT / record["manifest_path"]
        meta = json.loads(path.read_text())
        meta["bit_allocator"] = "uniform"
        path.write_text(json.dumps(meta))
        record["manifest_sha256"] = runner.sha256_file(path)
        d["ordering_diagnostics"][layout] = meta
        manifest_path.write_text(json.dumps(manifest))
        try:
            analysis.validate_manifest(args.output_dir, 256, 5, ("fixture",))
        except ValueError:
            pass
        else:
            raise AssertionError("C0 falsely labelled C3 was accepted")
        # All three optional order flags are required together; old four-layout CLI remains supported.
        command = [
            str(a.query_binary.resolve()),
            "--dataset-id",
            "fixture",
            "--points",
            d["input_csv"],
            "--a0-order",
            d["order_files"]["A0_input"]["path"],
            "--a3-order",
            d["order_files"]["A3_isotropic_hilbert"]["path"],
            "--a6-order",
            d["order_files"]["A6_rch"]["path"],
            "--source-sha256",
            checksum,
            "--output-dir",
            str(work / "legacy"),
        ]
        subprocess.run(command, check=True, capture_output=True, cwd=ROOT)
        old = list(csv.DictReader((work / "legacy/query_results.csv").open()))
        assert len(old) == 16
        bad_schedule = ["A0_input", "A0_input", "A3_isotropic_hilbert", "A6_rch"]
        assert (
            subprocess.run(
                command + ["--layout-order", ",".join(bad_schedule)],
                capture_output=True,
                cwd=ROOT,
            ).returncode
            != 0
        )

        assert (
            subprocess.run(
                command + ["--a6-c3-order", d["order_files"]["A6_rch_C3"]["path"]],
                capture_output=True,
                cwd=ROOT,
            ).returncode
            != 0
        )
    print(
        "PASS: 7 layouts; 8960 measured rows; 1792 NumPy oracle checks; 19 paired contrasts; native policy/artifact rejection; legacy CLI"
    )


if __name__ == "__main__":
    main()
