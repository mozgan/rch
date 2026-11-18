"""Adversarial gates for application-query evidence; no downloaded data needed."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from analysis.scripts import analyze_application_query_metrics as analysis
from experiments.application_layouts import APPLICATION_SCHEMA, APPLICATION_PROTOCOL, RULES
from analysis.scripts.make_paper_artifacts import render_synthetic_block_read_cache_miss


class ApplicationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(analysis, "REPO_ROOT", self.root).start()
        self.data = self.root / "run"
        self.data.mkdir()
        (self.root / "blob").write_text("checked input")
        self.ref = {"path": "blob", "sha256": analysis.digest(self.root / "blob")}

        def table(name, rows):
            with (self.root / name).open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            return {"path": name, "sha256": analysis.digest(self.root / name)}

        windows = table("windows.csv", [{"query_id": q} for q in ("q0", "q1")])
        correctness = []
        metrics = []
        for layout in analysis.LAYOUTS:
            for q in ("q0", "q1"):
                correctness.append(
                    {
                        "dataset_id": "fixture",
                        "layout_id": layout,
                        "query_id": q,
                        "result_count": 1,
                        "result_ids_sha256": "abc",
                        "oracle_match": "true",
                    }
                )
                for repeat in range(1, 6):
                    metrics.append(
                        {
                            **correctness[-1],
                            "repeat": repeat,
                            "wall_seconds": 0.02 if layout == "A0_input" else 0.01,
                            "cpu_seconds": 0.005,
                            "logical_bytes_read": 4096,
                            "pages_read": 1,
                            "candidate_pages": 1,
                            "records_examined": 2,
                            "selectivity": 0.5,
                            "process_read_bytes_delta": "",
                        }
                    )
        self.d = {
            "dataset_id": "fixture",
            "point_count": 2,
            "query_results": {
                "query_windows.csv": windows,
                "query_results.csv": table("correct.csv", correctness),
            },
            "warm_cache_query_metrics": table("metrics.csv", metrics),
            "order_files": {},
            "storage_integrity": {},
            "compression": {},
            "amortizable_preparation_seconds": {
                layout: 1.0 for layout in analysis.LAYOUTS
            },
        }
        for field, hashfield in [
            ("archive", "archive_sha256"),
            ("processed_file", "processed_sha256"),
            ("preprocessing_manifest", "preprocessing_manifest_sha256"),
            ("input_csv", "input_csv_sha256"),
        ]:
            self.d[field] = "blob"
            self.d[hashfield] = self.ref["sha256"]
        for layout in analysis.LAYOUTS:
            self.d["order_files"][layout] = {
                **self.ref,
                "manifest_path": "blob",
                "manifest_sha256": self.ref["sha256"],
            }
            self.d["storage_integrity"][layout] = {
                "page_count": 1,
                "page_file_bytes": 8192,
                "index_file_bytes": 4096,
                "query_memory": {"peak_rss_kib": None},
            }
            for field, hashfield in [
                ("manifest", "manifest_sha256"),
                ("page_file", "page_file_sha256"),
                ("index_file", "index_file_sha256"),
                ("query_memory_file", "query_memory_sha256"),
            ]:
                self.d["storage_integrity"][layout][field] = "blob"
                self.d["storage_integrity"][layout][hashfield] = self.ref["sha256"]
            self.d["compression"][layout] = {
                "compressed_file": "blob",
                "compressed_sha256": self.ref["sha256"],
                "compressed_bytes": 10,
                "compression_ratio": 0.1,
            }
        self.manifest = {
            "schema": APPLICATION_SCHEMA,
            "protocol": APPLICATION_PROTOCOL,
            "expected_dataset_ids": ["fixture"],
            "ordering": {"layouts": list(analysis.LAYOUTS), "layout_rules": RULES},
            "query_count_per_dataset_layout": 2,
            "cache_protocol": {"measured_workload_repeats": 5},
            "compression_protocol": {"level": 6},
            "datasets": [self.d],
        }
        self.d["layout_schedule"] = list(analysis.LAYOUTS)
        self.d["ordering_diagnostics"] = {}
        for layout in analysis.LAYOUTS:
            meta = {
                "point_count": 2, "bit_allocator": RULES[layout]["bit_allocator"],
                "method": "isotropic_hilbert" if layout == "A3_isotropic_hilbert" else "rch",
                "frame_estimator": "none" if layout == "A3_isotropic_hilbert" else "det_mcd",
                "refinement": "off", "controlled_frame_quantizer": False,
                "fixed_frame_domain_half_extent": 0, "uniform_bits": 10, "min_axis_bits": 1,
                "bits_axis": [10, 10, 10],
                "quantization_diagnostics": {key: 0 for key in (
                    "domain_clipped_point_count", "duplicate_hilbert_key_point_count",
                    "frame_core_outside_point_count")},
            }
            name = layout + ".json"
            (self.root / name).write_text(json.dumps(meta))
            self.d["order_files"][layout].update(manifest_path=name, manifest_sha256=analysis.digest(self.root / name))
            self.d["ordering_diagnostics"][layout] = meta
        self.save()

    def save(self):
        (self.data / "run_manifest.json").write_text(json.dumps(self.manifest))

    def analyze(self):
        return analysis.analyze(self.data, self.root / "out", 2, 5, ("fixture",))

    def mutate_metrics(self, change):
        p = self.root / "metrics.csv"
        with p.open() as f:
            rows = list(csv.DictReader(f))
        change(rows)
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        self.d["warm_cache_query_metrics"]["sha256"] = analysis.digest(p)
        self.save()

    def test_valid_matrix_and_A3_pair(self):
        result = self.analyze()
        self.assertEqual(len(result["summaries"]), len(analysis.LAYOUTS))
        self.assertTrue(
            any(
                r["reference"] == "A3_isotropic_hilbert"
                for r in result["paired_comparisons"]
            )
        )

    def test_missing_dataset(self):
        self.manifest["datasets"] = []
        self.save()
        with self.assertRaisesRegex(ValueError, "dataset"):
            self.analyze()

    def test_missing_manifest(self):
        (self.data / "run_manifest.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.analyze()

    def test_missing_repeat(self):
        self.mutate_metrics(lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.analyze()

    def test_duplicate_row(self):
        self.mutate_metrics(lambda rows: rows.append(rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.analyze()

    def test_false_oracle_boolean_cannot_hide_bad_hash(self):
        self.mutate_metrics(lambda rows: rows[0].update(result_ids_sha256="bad"))
        with self.assertRaisesRegex(ValueError, "oracle"):
            self.analyze()

    def test_tampered_file(self):
        (self.root / "blob").write_text("changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.analyze()

    def test_frozen_full_workload_and_changed_executor_window(self):
        import shutil

        from experiments.runners.run_application_query_smoke import (
            write_full_query_matrix,
        )

        metadata = write_full_query_matrix(
            self.root / "frozen.csv", [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
        )
        self.d["query_workload"] = {**metadata, "file": "frozen.csv"}
        shutil.copyfile(self.root / "frozen.csv", self.root / "windows.csv")
        self.d["query_results"]["query_windows.csv"]["sha256"] = analysis.digest(
            self.root / "windows.csv"
        )
        with (self.root / "windows.csv").open() as f:
            windows = list(csv.DictReader(f))
        for name, measured in [("correct.csv", False), ("metrics.csv", True)]:
            with (self.root / name).open() as f:
                templates = list(csv.DictReader(f))
            rows = []
            for layout in analysis.LAYOUTS:
                pattern = next(r for r in templates if r["layout_id"] == layout)
                for window in windows:
                    for repeat in range(1, 6) if measured else (0,):
                        row = {**pattern, "query_id": window["query_id"]}
                        if measured:
                            row["repeat"] = repeat
                        rows.append(row)
            with (self.root / name).open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        self.d["query_results"]["query_results.csv"]["sha256"] = analysis.digest(
            self.root / "correct.csv"
        )
        self.d["warm_cache_query_metrics"]["sha256"] = analysis.digest(
            self.root / "metrics.csv"
        )
        self.manifest["query_count_per_dataset_layout"] = 256
        self.save()
        analysis.analyze(self.data, self.root / "full_analysis", 256, 5, ("fixture",))
        windows[0]["min_x"] = str(float(windows[0]["min_x"]) + 0.001)
        with (self.root / "windows.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(windows[0]))
            writer.writeheader()
            writer.writerows(windows)
        self.d["query_results"]["query_windows.csv"]["sha256"] = analysis.digest(
            self.root / "windows.csv"
        )
        self.save()
        with self.assertRaisesRegex(ValueError, "coordinates"):
            analysis.analyze(
                self.data, self.root / "bad_analysis", 256, 5, ("fixture",)
            )

    def test_source_manifest_checksum_is_checked(self):
        self.d["source_manifest"] = "blob"
        self.d["source_manifest_sha256"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            analysis.analyze(self.data, self.root / "bad_source", 2, 5, ("fixture",))

    def test_artifact_tables_and_manifest(self):
        from analysis.scripts import make_application_artifacts as artifacts

        self.d["geometry"] = {"bbox_aspect_ratio": 2.0}
        self.save()
        real_results = self.root / "real_results"
        for dataset in ("stanford_bunny", "stanford_armadillo", "usgs_cameron_peak"):
            for layout in ("A3_isotropic_hilbert", "A5_pca_compact_hilbert", "A6_rch"):
                for mode in ("off", "all"):
                    directory = real_results / mode / "manifests"
                    directory.mkdir(parents=True, exist_ok=True)
                    for seed in range(5):
                        (
                            directory
                            / f"{dataset}__{layout}__C3_frame_core_occupancy__D0__s{seed}.manifest.json"
                        ).write_text(
                            json.dumps(
                                {
                                    "sort_seconds": 0.1,
                                    "timing_breakdown_seconds": {
                                        "refinement": 0.02 if mode == "all" else 0.0
                                    },
                                }
                            )
                        )
        real_analyze = analysis.analyze
        with patch.object(
            artifacts,
            "analyze",
            side_effect=lambda source, output, **kwargs: real_analyze(
                source, output, 2, 5, ("fixture",)
            ),
        ):
            artifacts.generate(self.data, self.root / "generated", real_results)
        checker = (
            Path(__file__).resolve().parents[2]
            / "analysis/scripts/check_application_artifacts.py"
        )
        command = [
            sys.executable,
            str(checker),
            "--input-root",
            str(self.data),
            "--output-root",
            str(self.root / "generated"),
        ]
        subprocess.run(command, check=True, capture_output=True)
        with (self.root / "generated/tables/table_application_query.tex").open(
            "a"
        ) as handle:
            handle.write("% altered after generation\n")
        self.assertNotEqual(
            subprocess.run(command, check=False, capture_output=True).returncode, 0
        )
        self.assertIn(
            "tab:application_paired",
            (self.root / "generated/tables/table_application_query.tex").read_text(),
        )
        self.assertTrue(
            (
                self.root / "generated/outputs/application_query/evidence.md"
            ).exists()
        )

    def test_missing_run_has_no_numeric_performance_claim(self):
        from analysis.scripts.make_application_artifacts import generate

        generate(self.root / "missing", self.root / "generated")
        state = json.loads(
            (
                self.root / "generated/stats/application_artifacts_manifest.json"
            ).read_text()
        )
        self.assertEqual(state["status"], "unavailable_full_matrix")

    def test_unavailable_perf_is_explicit(self):
        result = render_synthetic_block_read_cache_miss(
            SimpleNamespace(synthetic_rows=[]), self.root / "cache.pdf"
        )
        self.assertEqual(result["status"], "unavailable_perf_counters")
        self.assertTrue((self.root / "cache.pdf").is_file())


if __name__ == "__main__":
    unittest.main()
