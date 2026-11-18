"""Exercise Make orchestration with harmless stand-ins, plus isolated cleanup."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.sync_paper_figures import sync_figures

ROOT = Path(__file__).resolve().parents[2]


class BuildWorkflowsTest(unittest.TestCase):
    def test_paper_figures_replace_stale_copies_and_ignore_commented_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated, figures = root / 'generated', root / 'figures'
            generated.mkdir()
            figures.mkdir()
            manuscript = root / 'manuscript.tex'
            text = '% \\includegraphics{missing.pdf}\n\\includegraphics[width=1cm]{plot.eps}\n'
            manuscript.write_text(text)
            (generated / 'plot.eps').write_bytes(b'new eps')
            (generated / 'plot.pdf').write_bytes(b'new pdf')
            (figures / 'plot.eps').write_bytes(b'stale eps')
            names = sync_figures(manuscript, generated, figures)
            self.assertEqual(names, ['plot.eps', 'plot.pdf'])
            self.assertEqual((figures / 'plot.eps').read_bytes(), b'new eps')
            self.assertEqual((figures / 'plot.pdf').read_bytes(), b'new pdf')
            self.assertEqual(manuscript.read_text(), text)

    def test_missing_paper_figure_fails_before_replacing_any_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated, figures = root / 'generated', root / 'figures'
            generated.mkdir()
            figures.mkdir()
            manuscript = root / 'manuscript.tex'
            manuscript.write_text('\\includegraphics{present.pdf}\n\\includegraphics{missing.pdf}\n')
            (generated / 'present.pdf').write_bytes(b'new')
            (figures / 'present.pdf').write_bytes(b'old')
            with self.assertRaises(FileNotFoundError):
                sync_figures(manuscript, generated, figures)
            self.assertEqual((figures / 'present.pdf').read_bytes(), b'old')

    def capture(self, target, fail=""):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            recorder = work / "make-recorder"
            log = work / "calls.jsonl"
            recorder.write_text(
                f"#!{sys.executable}\n"
                "import json,os,sys\n"
                "with open(os.environ['WORKFLOW_CALL_LOG'],'a') as out:\n"
                " out.write(json.dumps(sys.argv[1:])+'\\n')\n"
                "sys.exit(9 if sys.argv[1] == os.environ.get('WORKFLOW_FAIL_TARGET') else 0)\n"
            )
            recorder.chmod(0o755)
            result = subprocess.run(
                ["make", "--no-print-directory", target, f"MAKE={recorder}"],
                cwd=ROOT,
                env={
                    **os.environ,
                    "WORKFLOW_CALL_LOG": str(log),
                    "WORKFLOW_FAIL_TARGET": fail,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            calls = [json.loads(line)[0] for line in log.read_text().splitlines()]
            return result, calls

    def test_all_targets_runs_each_phase_without_repeating_production_consumers(self):
        result, calls = self.capture("all-targets")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in [
            "venv",
            "real-data",
            "clean",
            "clean-artifacts",
            "demo-data",
            "format",
            "test-pyramid",
            "release-clang",
            "release-gcc",
            "asan",
            "ubsan",
            "tsan",
            "fuzz",
            "coverage",
            "repro",
            "repro-smoke",
            "examples",
            "example-basic",
            "test-cli",
            "test-cgal",
            "bench-micro-run",
            "bench",
        ]:
            self.assertEqual(calls.count(target), 1, target)
        self.assertEqual(
            calls[:7],
            ["venv", "real-data", "clean", "clean-artifacts", "demo-data", "format", "test-pyramid"],
        )
        self.assertEqual(calls.count("test-release"), 3)
        self.assertLess(calls.index("clean-artifacts"), calls.index("test-pyramid"))
        self.assertEqual(calls[-1], "bench")
        self.assertNotIn("paper-pdf", calls)
        self.assertNotIn("app-query", calls)  # Owned by the nested benchmark suite.

    def test_failed_data_preparation_stops_before_builds_and_benchmarks(self):
        for producer in ("real-data", "demo-data"):
            with self.subTest(producer=producer):
                result, calls = self.capture("all-targets", fail=producer)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[-1], producer)
                for consumer in ("format", "test-pyramid", "release-clang", "bench", "paper-pdf"):
                    self.assertNotIn(consumer, calls)
                if producer == "real-data":
                    self.assertNotIn("clean", calls)
                    self.assertNotIn("clean-artifacts", calls)

    def test_bench_defers_integration_until_all_production_groups(self):
        result, calls = self.capture("bench")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls[:4],
            ["bench-synthetic", "bench-real", "bench-independent", "bench-cgal"],
        )
        self.assertNotIn("bench-test", calls)
        self.assertIn("test-benchmark-resume", calls)
        self.assertEqual(calls[-2:], ["bench-extended", "test-integration"])

    def test_extended_order_includes_cache_and_workflow_before_artifacts(self):
        result, calls = self.capture("bench-extended")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "bench-test",
                "bench-c1-resolution",
                "bench-clamping-intervention",
                "bench-cost-stability",
                "app-query",
                "bench-tree",
                "bench-dbms",
                "bench-application-cache",
                "bench-application-workflow",
                "paper-artifacts",
                "validate-extended-benchmarks",
                "validate-application-cache",
                "validate-application-workflow",
            ],
        )

    def test_failed_producer_stops_before_consumers_and_publication(self):
        for producer in ("app-query", "bench-application-cache", "bench-application-workflow"):
            with self.subTest(producer=producer):
                result, calls = self.capture("bench-extended", fail=producer)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[-1], producer)
                self.assertNotIn("paper-artifacts", calls)

    def test_cleanup_in_isolated_tree_removes_nested_outputs_but_keeps_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            disposable = [
                "experiments/outputs/cache/nested/metrics.csv",
                "experiments/logs/pipeline/run.json",
                "analysis/generated/nested/chart.pdf",
                "paper/build/manuscript.pdf",
            ]
            retained = [
                "data/raw/input.laz",
                "backups/sources/archive.tar.gz",
                "paper/manuscript.tex",
                "analysis/generated/outputs/.gitkeep",
            ]
            for name in disposable + retained:
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            result = subprocess.run(
                [
                    "make",
                    "--no-print-directory",
                    "-f",
                    str(ROOT / "Makefile"),
                    "clean-artifacts",
                    f"PYTHON={sys.executable}",
                ],
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in disposable:
                self.assertFalse((work / name).exists(), name)
            for name in retained:
                self.assertEqual((work / name).read_text(), "fixture", name)


if __name__ == "__main__":
    unittest.main()
