#!/usr/bin/env python3
"""Tiny-cloud workflow/oracle/resume/artifact tests; never use downloaded scenes."""
import csv
import hashlib
import json
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_workflow import digest, freeze_workloads, validate_run, write_json
from experiments.runners.run_application_workflow import run
from analysis.scripts.make_application_workflow_artifacts import generate, summaries

BINARY = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if BINARY is None:
            raise RuntimeError("pass the workflow executable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.points = [(float(i % 11), float((i // 11) % 13), float(i // 143)) for i in range(291)] + [(0., 0., 0.)]
        cls.output = cls.root / "run"
        cls.args = SimpleNamespace(output_dir=cls.output, binary=BINARY, dataset=["fixture"],
                                   query_counts=[256, 512, 1024], repeats=2, seed=2026,
                                   keep_work_files=False, resume=False)

        def prepare(dataset, output, counts, seed):
            base = output / "inputs/fixture"
            base.mkdir(parents=True)
            path = base / "points.csv"
            path.write_text("".join(",".join(map(str, p)) + "\n" for p in cls.points))
            workloads = freeze_workloads(cls.points, counts, base / "workloads", seed)
            for w in workloads.values():
                w["path"] = str((base / w["path"]).relative_to(output))
            return {"dataset_id": dataset, "point_count": len(cls.points),
                    "input": {"path": str(path.relative_to(output)), "sha256": digest(path)},
                    "workloads": workloads, "provenance": {"scope": "tiny test fixture"}}

        run(cls.args, prepare)
        cls.preparer = staticmethod(prepare)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_sizes_and_continuous_phases(self):
        manifest, rows = validate_run(self.output)
        self.assertEqual(len(rows), 18)
        self.assertEqual({r["query_count"] for r in rows}, {256, 512, 1024})
        self.assertTrue(all(r["ordering_calls"] == 1 for r in rows))
        for trial in manifest["trials"]:
            self.assertTrue(all(not (self.output / v["path"]).exists() for v in trial["outputs"].values()))

    def test_nested_workloads_are_not_repeated_256_windows(self):
        manifest, _ = validate_run(self.output)
        workloads = manifest["datasets"][0]["workloads"]
        windows = [(self.output / workloads[str(n)]["path"]).read_text().splitlines()
                   for n in (256, 512, 1024)]
        self.assertEqual(windows[1][:256], windows[0])
        self.assertEqual(windows[2][:512], windows[1])
        self.assertEqual(len(set(windows[2])), 1024)
        self.assertEqual(len({tuple(line.split("\t")[1:7]) for line in windows[2]}), 1024)
        groups = [line.split("\t")[0].split("_")[1] for line in windows[2]]
        self.assertEqual([groups.count(k) for k in ("small", "medium", "large")], [344, 340, 340])

    def test_resume_does_not_execute_completed_workflows(self):
        before = (self.output / "run_manifest.json").read_bytes()
        self.args.resume = True
        try:
            run(self.args, self.preparer)
        finally:
            self.args.resume = False
        after = json.loads((self.output / "run_manifest.json").read_text())
        self.assertEqual(after["trials"], json.loads(before)["trials"])

    def test_transferred_package_uses_relative_paths(self):
        transferred = self.root / "another_machine"
        shutil.copytree(self.output, transferred)
        _, rows = validate_run(transferred)
        self.assertEqual(len(rows), 18)

    def test_resume_rejects_changed_workload(self):
        counts = self.args.query_counts
        self.args.query_counts = [256]
        self.args.resume = True
        try:
            with self.assertRaisesRegex(ValueError, "resume identity"):
                run(self.args, self.preparer)
        finally:
            self.args.query_counts = counts
            self.args.resume = False

    def test_artifact_generation_and_tamper_gate(self):
        destination = self.root / "artifacts"
        generate(self.output, destination)
        generate(self.output, destination, True)
        path = destination / "outputs/application_workflow/summary.csv"
        path.write_text(path.read_text() + "tampered\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            generate(self.output, destination, True)

    def test_missing_or_false_continuous_timing_is_rejected(self):
        path = self.output / "run_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        metric = self.output / manifest["trials"][0]["metrics"]["path"]
        old_metric = metric.read_bytes()
        value = json.loads(old_metric)
        value["total_seconds"] += 1
        write_json(metric, value)
        manifest["trials"][0]["metrics"]["sha256"] = digest(metric)
        write_json(path, manifest)
        try:
            with self.assertRaisesRegex(ValueError, "partition"):
                validate_run(self.output)
        finally:
            metric.write_bytes(old_metric)
            path.write_bytes(original)

    def test_materialized_oracle_hash_gate(self):
        path = self.output / "run_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        manifest["trials"][0]["outputs"]["results.bin"]["sha256"] = "0" * 64
        write_json(path, manifest)
        try:
            with self.assertRaisesRegex(ValueError, "materialized"):
                validate_run(self.output)
        finally:
            path.write_bytes(original)

    def test_missing_trial_is_rejected(self):
        path = self.output / "run_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        manifest["trials"].pop()
        write_json(path, manifest)
        try:
            with self.assertRaisesRegex(ValueError, "missing workflow"):
                validate_run(self.output)
        finally:
            path.write_bytes(original)

    def test_missing_io_is_not_zero(self):
        manifest, rows = validate_run(self.output)
        rows[0]["storage_read_bytes"] = None
        summary, _ = summaries(manifest, rows)
        group = next(r for r in summary if (r["dataset_id"], r["query_count"], r["layout"]) ==
                     (rows[0]["dataset_id"], rows[0]["query_count"], rows[0]["layout"]))
        self.assertEqual(group["storage_read_bytes_median"], "")
        self.assertEqual(group["storage_read_bytes_available"], 1)

    def test_empty_boundary_duplicate_results_and_bad_oracle(self):
        points = self.root / "boundary.csv"
        points.write_text("0,0,0\n1,1,1\n1,1,1\n2,2,2\n")
        windows = [(-1, -1, -1, 3, 3, 3), (5, 5, 5, 6, 6, 6), (1, 1, 1, 1, 1, 1)]
        oracle = self.root / "boundary.tsv"
        expected = [[0, 1, 2, 3], [], [1, 2]]
        oracle.write_text("".join(
            "\t".join([f"q{i}", *map(str, bounds), str(len(ids)),
                        hashlib.sha256(b"".join(struct.pack("<Q", v) for v in ids)).hexdigest()]) + "\n"
            for i, (bounds, ids) in enumerate(zip(windows, expected))))
        for layout in ("A0_input", "A3_isotropic_hilbert", "A6_rch_C3"):
            result = subprocess.run([str(BINARY), str(points), str(oracle), layout,
                                     str(self.root / ("boundary_" + layout))], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        oracle.write_text(oracle.read_text().replace(hashlib.sha256(b"").hexdigest(), "0" * 64))
        work = self.root / "bad_oracle"
        result = subprocess.run([str(BINARY), str(points), str(oracle), "A0_input", str(work)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((work / "metrics.json").exists())


if __name__ == "__main__":
    unittest.main()
