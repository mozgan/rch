#!/usr/bin/env python3
"""Actual Linux cache interventions, independent oracle, provenance and resume controls."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.runners import run_application_cache as runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("storage_binary", type=Path)
    parser.add_argument("probe_binary", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(
        prefix="application_cache_", dir=ROOT / "build"
    ) as name:
        work = Path(name)
        source = work / "source"
        source.mkdir()
        points = [(i % 11, (i // 11) % 13, i // 143) for i in range(291)]
        xyz = work / "points.csv"
        xyz.write_text("".join(f"{x},{y},{z}\n" for x, y, z in points))
        order = work / "order.csv"
        order.write_text(
            "rank,raw_index,key\n"
            + "".join(f"{i},{i},{i}\n" for i in range(len(points)))
        )
        bounds = [
            (-1, -1, -1, 20, 20, 20),
            (50, 50, 50, 60, 60, 60),
            (0, 0, 0, 0, 0, 0),
            (0, 0, 2, 10, 12, 2),
            (2, 3, 0, 6, 7, 1),
        ]
        queries = work / "queries.csv"
        queries.write_text(
            "query_id,min_x,min_y,min_z,max_x,max_y,max_z\n"
            + "".join(
                f"q{i}," + ",".join(map(str, b)) + "\n" for i, b in enumerate(bounds)
            )
        )
        results = source / "results"
        command = [
            str(args.storage_binary.resolve()),
            "--dataset-id",
            "fixture",
            "--points",
            str(xyz),
            "--a0-order",
            str(order),
            "--a3-order",
            str(order),
            "--a6-order",
            str(order),
            "--source-sha256",
            runner.sha(xyz),
            "--query-windows",
            str(queries),
            "--output-dir",
            str(results),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        oracle = results / "query_results.csv"
        oracle_rows = runner.read_csv(oracle)
        # Independent Python coordinate scan, including inclusive boundaries and final partial page.
        for row in oracle_rows:
            b = bounds[int(row["query_id"][1:])]
            ids = [
                i
                for i, xyz in enumerate(points)
                if all(b[a] <= xyz[a] <= b[a + 3] for a in range(3))
            ]
            digest = hashlib.sha256(
                b"".join(struct.pack("<Q", i) for i in ids)
            ).hexdigest()
            assert (
                int(row["result_count"]) == len(ids)
                and row["result_ids_sha256"] == digest
            )
        layouts = sorted({r["layout_id"] for r in oracle_rows})
        storage = {}
        for layout in layouts:
            page, index = results / f"{layout}.page", results / f"{layout}.index"
            storage[layout] = {
                "page_file": str(page),
                "page_file_sha256": runner.sha(page),
                "index_file": str(index),
                "index_file_sha256": runner.sha(index),
            }
        q = results / "query_windows.csv"
        manifest = {
            "source_sha256": {},
            "query_count_per_dataset_layout": len(bounds),
            "datasets": [
                {
                    "dataset_id": "fixture",
                    "layout_schedule": layouts,
                    "query_results": {
                        "query_windows.csv": {"path": str(q), "sha256": runner.sha(q)},
                        "query_results.csv": {
                            "path": str(oracle),
                            "sha256": runner.sha(oracle),
                        },
                    },
                    "storage_integrity": storage,
                }
            ],
        }
        runner.write_json(source / "run_manifest.json", manifest)
        output = work / "measured"
        base = [
            sys.executable,
            str(ROOT / "experiments/runners/run_application_cache.py"),
            "--application-root",
            str(source),
            "--output-dir",
            str(output),
            "--probe-bin",
            str(args.probe_binary.resolve()),
            "--repeats",
            "2",
        ]
        plan = subprocess.run(base, check=True, capture_output=True, text=True)
        assert json.loads(plan.stdout)["measurements"] == 80 and not output.exists()
        measured = subprocess.run(
            base + ["--run"], check=False, capture_output=True, text=True
        )
        if measured.returncode:
            raise RuntimeError(
                measured.stderr
                + "\n"
                + "\n".join(p.read_text() for p in output.glob("*.log"))
            )
        before = {
            p.name: (runner.sha(p), p.stat().st_mtime_ns) for p in output.glob("*.csv")
        }
        subprocess.run(
            base + ["--run", "--resume"], check=True, capture_output=True, text=True
        )
        after = {
            p.name: (runner.sha(p), p.stat().st_mtime_ns)
            for p in output.glob("*.attempt*.csv")
        }
        assert all(before[k] == v for k, v in after.items())
        subprocess.run(
            base + ["--validate-only"], check=True, capture_output=True, text=True
        )
        # Simulate a process interruption after a child wrote metrics but before its
        # successful layout checkpoint. Earlier layouts must not be remeasured.
        journal_path = output / "run_manifest.json"
        journal = json.loads(journal_path.read_text())
        interrupted = f"fixture__{layouts[-1]}"
        interrupted_metrics = output / journal["tasks"][interrupted]["metrics"]
        old_metrics_hash = runner.sha(interrupted_metrics)
        journal["status"] = "running"
        journal["tasks"][interrupted]["status"] = "running"
        journal["tasks"][interrupted].pop("metrics_sha256")
        journal["tasks"][interrupted]["attempts"] = []
        runner.write_json(journal_path, journal)
        assert (
            subprocess.run(
                base + ["--validate-only"], check=False, capture_output=True
            ).returncode
            != 0
        )
        subprocess.run(
            base + ["--run", "--resume"], check=True, capture_output=True, text=True
        )
        recovered = json.loads(journal_path.read_text())
        assert recovered["tasks"][interrupted]["attempt"] == 2
        assert runner.sha(interrupted_metrics) == old_metrics_hash
        for task_key, item in recovered["tasks"].items():
            if task_key != interrupted:
                path = output / item["metrics"]
                assert before[path.name] == (runner.sha(path), path.stat().st_mtime_ns)
        subprocess.run(
            base + ["--validate-only"], check=True, capture_output=True, text=True
        )
        publisher = [sys.executable, str(ROOT / "analysis/scripts/make_application_cache_artifacts.py"),
                     "--input-root", str(output), "--artifact-root", str(work / "published")]
        subprocess.run(publisher, check=True, capture_output=True, text=True)
        subprocess.run(publisher + ["--validate-only"], check=True, capture_output=True, text=True)
        assert (work / "published/figures/fig_application_cache_latency.pdf").is_file()
        assert (work / "published/tables/table_application_cache.tex").is_file()
        assert (
            subprocess.run(
                base + ["--run"], check=False, capture_output=True
            ).returncode
            != 0
        )
        assert (
            subprocess.run(
                base + ["--resume", "--run", "--repeats", "3"],
                check=False,
                capture_output=True,
            ).returncode
            != 0
        )
        config = SimpleNamespace(
            application_root=source,
            probe_bin=args.probe_binary.resolve(),
            dataset=None,
            repeats=2,
            seed=2026,
        )
        _, tasks = runner.prepare(config)
        first = tasks[0]
        metrics = next(output.glob(f"fixture__{first['layout_id']}.attempt*.csv"))
        original = metrics.read_text()
        records = runner.read_csv(metrics)
        for change in ("residency", "oracle", "duplicate"):
            rows = [dict(r) for r in records]
            if change == "residency":
                row = next(r for r in rows if r["cache_mode"] == "cold_page_cache")
                row["resident_pages_before"] = "1"
            elif change == "oracle":
                rows[0]["result_sha256"] = "0" * 64
            else:
                rows.append(rows[0])
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            metrics.write_text(stream.getvalue())
            try:
                runner.validate_metrics(metrics, first, 2)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted invalid {change}")
        metrics.write_text(original)
        runner.write_json(source / "run_manifest.json", {**manifest, "datasets": []})
        try:
            runner.prepare(config)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted an empty application task selection")
        runner.write_json(source / "run_manifest.json", manifest)
        # Input drift fails before producing a new experiment, not after a measurement.
        page = Path(first["page"])
        with page.open("r+b") as target:
            target.seek(4100)
            target.write(b"BAD!")
        assert (
            subprocess.run(
                base + ["--validate-only"], check=False, capture_output=True
            ).returncode
            != 0
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "layouts": 4,
                    "queries": 5,
                    "repeats": 2,
                    "measured_rows": 80,
                    "recovery_control_additional_rows": 20,
                    "independent_oracle": True,
                    "cache_residency_checked": True,
                    "plan_read_only": True,
                    "resume_preserves_completed_metrics": True,
                    "interrupted_layout_retried_completed_layouts_preserved": True,
                    "bad_residency_oracle_duplicate_and_input_drift_rejected": True,
                }
            )
        )


if __name__ == "__main__":
    main()
