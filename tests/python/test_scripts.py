"""Unit tests for repository helper scripts."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import struct
import sys
import tarfile
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import yaml

from scripts.convert_dataset import (
    parse_ply_header,
    read_ply_points,
    write_ascii_ply,
)
from scripts.create_demo_dataset import (
    create_demo_dataset,
    write_ply,
    write_reproducible_tar_gz,
)
from scripts.download_dataset import ensure_dataset, selected_datasets
from scripts.verify_demo_artifacts import (
    REQUIRED_TABLE_CSVS,
    check_required_table_csvs,
    expected_refinement_for_row,
    finite_values,
    nullish_locations,
)

ROOT = Path(__file__).resolve().parents[2]


class ConvertDatasetScriptTest(unittest.TestCase):
    """Edge-case coverage for PLY conversion helpers."""

    def test_parse_ply_header_accepts_crlf_and_ignores_comment_keyword(self) -> None:
        """`end_header` is recognized as a keyword line, not a substring."""
        data = (
            b"ply\r\n"
            b"format ascii 1.0\r\n"
            b"comment literal end_header should not terminate\r\n"
            b"element vertex 1\r\n"
            b"property float x\r\n"
            b"property float y\r\n"
            b"property float z\r\n"
            b"end_header\r\n"
            b"1 2 3\r\n"
        )
        header = parse_ply_header(data)
        self.assertEqual(header.fmt, "ascii")
        self.assertEqual(header.vertex_count, 1)
        self.assertEqual(header.header_bytes, data.index(b"1 2 3"))

    def test_read_ascii_ply_rejects_short_vertex_rows(self) -> None:
        """ASCII rows must contain every header-declared vertex property."""
        data = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
            b"1 2\n"
        )
        with self.assertRaises(ValueError):
            read_ply_points(data)

    def test_read_binary_big_endian_vertices(self) -> None:
        """Binary PLY scalar decoding honors header-declared endianness."""
        header = (
            b"ply\nformat binary_big_endian 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
        )
        payload = struct.pack(">fff", 1.25, -2.5, 3.75)
        points, parsed = read_ply_points(header + payload)
        self.assertEqual(parsed.fmt, "binary_big_endian")
        self.assertEqual(points, [(1.25, -2.5, 3.75)])

    def test_write_ascii_ply_uses_double_precision_and_rejects_nan(self) -> None:
        """Canonical output preserves binary64 text and fails closed on NaN."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "points.ply"
            write_ascii_ply(path, [(1.0 / 3.0, 2.0, 3.0)])
            text = path.read_text(encoding="utf-8")
            self.assertIn("property double x", text)
            self.assertIn("0.33333333333333331", text)
            with self.assertRaises(ValueError):
                write_ascii_ply(path, [(float("nan"), 0.0, 0.0)])


class CreateAndDownloadScriptsTest(unittest.TestCase):
    """Edge-case coverage for demo archive and downloader helpers."""

    def test_write_ply_declares_expected_vertex_count(self) -> None:
        """Demo PLY bytes expose a point-only ASCII vertex element."""
        payload = write_ply([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
        self.assertIn(b"element vertex 2\n", payload)
        self.assertTrue(payload.endswith(b"4 5 6\n"))

    def test_write_ply_rejects_non_finite_points(self) -> None:
        """Demo PLY writer fails closed before emitting NaN/Inf fixtures."""
        with self.assertRaises(ValueError):
            write_ply([(float("nan"), 0.0, 0.0)])

    def test_reproducible_tar_gz_is_byte_identical(self) -> None:
        """Fixed gzip/tar metadata makes repeated archives identical."""
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.tar.gz"
            second = Path(tmp) / "second.tar.gz"
            write_reproducible_tar_gz(first, "cloud.ply", b"payload")
            write_reproducible_tar_gz(second, "cloud.ply", b"payload")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with gzip.open(first, "rb") as gz:
                with tarfile.open(fileobj=io.BytesIO(gz.read()), mode="r:") as tar:
                    member = tar.getmember("cloud.ply")
                    self.assertEqual(member.mtime, 0)
                    self.assertEqual(member.uid, 0)
                    self.assertEqual(member.mode, 0o644)

    def test_create_demo_dataset_accepts_external_temp_output_roots(self) -> None:
        """The demo generator can be smoke-tested outside the repository tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_demo_dataset(
                Namespace(
                    source_dir=root / "source",
                    manifest=root / "rch_demo.yml",
                    processed_dir=root / "processed",
                    real_catalog=root / "catalog.yml",
                    synthetic_locality_runlist=root
                    / "runlists"
                    / "table_3_locality.yaml",
                    synthetic_outlier_runlist=root
                    / "runlists"
                    / "table_4_outlier.yaml",
                    synthetic_runtime_runlist=root
                    / "runlists"
                    / "table_5_runtime.yaml",
                    real_runlist=root / "runlists" / "table_2_dataset_summary.yaml",
                    a7_output_dir=root / "a7",
                )
            )

            self.assertEqual(Path(result["manifest"]), root / "rch_demo.yml")
            manifest = yaml.safe_load(
                (root / "rch_demo.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["datasets"]), 2)
            self.assertTrue(Path(manifest["datasets"][0]["url"]).is_absolute())

    def test_selected_datasets_reports_missing_ids(self) -> None:
        """Manifest filtering preserves order and fails on unknown ids."""
        manifest = {"datasets": [{"id": "b"}, {"id": "a"}]}
        self.assertEqual(
            [item["id"] for item in selected_datasets(manifest, {"a", "b"})],
            ["b", "a"],
        )
        with self.assertRaises(ValueError):
            selected_datasets(manifest, {"missing"})

    def test_ensure_dataset_verifies_local_source_sha256(self) -> None:
        """Local-source downloads are copied then checked against SHA-256."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            source.write_bytes(b"abc")
            digest = hashlib.sha256(b"abc").hexdigest()
            dataset = {
                "id": "local",
                "filename": "local.bin",
                "url": str(source),
                "sha256": digest,
            }
            target = ensure_dataset(dataset, root / "raw")
            self.assertEqual(target.read_bytes(), b"abc")

            bad = dict(dataset)
            bad["filename"] = "bad.bin"
            bad["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                ensure_dataset(bad, root / "raw")
            self.assertFalse((root / "raw" / "bad.bin").exists())


class VerifyDemoArtifactsScriptTest(unittest.TestCase):
    """Small pure-function checks for demo artifact verifier helpers."""

    def test_required_table_csvs_match_generated_table_contract(self) -> None:
        """Verifier table requirements match the current table-builder outputs."""
        self.assertEqual(
            REQUIRED_TABLE_CSVS,
            (
                "table_synthetic_locality_summary.csv",
                "table_synthetic_contamination_stability.csv",
                "table_synthetic_runtime_summary.csv",
                "table_synthetic_hypothesis_tests.csv",
                "table_synthetic_hypothesis_tests_by_bit_rule.csv",
                "table_real_dataset_summary.csv",
                "table_real_directional_h1_comparisons.csv",
            ),
        )

    def test_check_required_table_csvs_accepts_current_contract(self) -> None:
        """All current required table CSVs are readable with a minimal row."""
        with tempfile.TemporaryDirectory() as tmp:
            tables = Path(tmp)
            for filename in REQUIRED_TABLE_CSVS:
                (tables / filename).write_text("column\nvalue\n", encoding="utf-8")
            check_required_table_csvs(tables)

    def test_finite_values_counts_only_finite_numbers(self) -> None:
        """Blank, NaN, and Inf cells are excluded from finite counts."""
        rows = [
            {"metric": "1.0"},
            {"metric": ""},
            {"metric": "nan"},
            {"metric": "inf"},
            {"metric": "-2.5"},
        ]
        self.assertEqual(finite_values(rows, "metric"), 2)

    def test_nullish_locations_recurses_nested_json(self) -> None:
        """Nested None/NaN positions are reported with stable paths."""
        value = {"a": [1.0, None], "b": {"c": float("nan")}}
        self.assertEqual(
            nullish_locations(value, "root"),
            ["root.a[1]", "root.b.c"],
        )

    def test_expected_refinement_keeps_input_and_external_special_cases(self) -> None:
        """Demo verifier mirrors runner refinement tags for non-refinable rows."""
        self.assertEqual(
            expected_refinement_for_row({"algorithm_id": "A0_input"}, "all"), "off"
        )
        self.assertEqual(
            expected_refinement_for_row(
                {"algorithm_id": "A7_cgal_spatial_sort"}, "all"
            ),
            "external",
        )
        self.assertEqual(
            expected_refinement_for_row({"algorithm_id": "A6_rch"}, "all"), "all"
        )


class DemoPerfShimTest(unittest.TestCase):
    """Contract tests for tools/demo/perf used by the demo fixture utilities."""

    def test_demo_perf_emits_parseable_cache_counters(self) -> None:
        """Supported perf-stat calls return deterministic M8 counter CSV."""
        completed = subprocess.run(
            [
                str(ROOT / "tools/demo/perf"),
                "stat",
                "-x,",
                "-e",
                "cache-references,cache-misses",
                "true",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("1000,,cache-references,", completed.stderr)
        self.assertIn("100,,cache-misses,", completed.stderr)

    def test_demo_perf_rejects_unsupported_event_set(self) -> None:
        """The shim fails closed if the runner asks for different counters."""
        completed = subprocess.run(
            [
                str(ROOT / "tools/demo/perf"),
                "stat",
                "-x,",
                "-e",
                "cache-references",
                "true",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("cache-references,cache-misses", completed.stderr)

    def test_demo_perf_returns_wrapped_command_failure(self) -> None:
        """Probe failures propagate instead of producing fake counters."""
        completed = subprocess.run(
            [
                str(ROOT / "tools/demo/perf"),
                "stat",
                "-x,",
                "-e",
                "cache-references,cache-misses",
                "--",
                "false",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn("cache-references", completed.stderr)


class ArtifactInputRoutingTest(unittest.TestCase):
    """Artifact readers reuse complete runs without changing benchmark writers."""

    def test_reader_fallback_writers_and_explicit_overrides(self):
        makefile = (ROOT / "Makefile").read_text()
        routing = makefile.split("# Artifact readers may reuse", 1)[1].split("\n", 1)[1].split("# CTest regexes", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "Makefile"
            fixture.write_text(
                "INDEPENDENT_OUTPUT_DIR ?= experiments/outputs/independent_benchmarks\n"
                "REAL_OUTPUT_DIR ?= experiments/outputs/real_dataset\n"
                "APPLICATION_QUERY_OUTPUT_DIR ?= experiments/outputs/application_query/full_benchmark\n"
                + routing
                + "\npaper-artifacts test-integration bench-real bench-independent:\n"
                + "\t@printf '%s\\n' '$(INDEPENDENT_OUTPUT_DIR)' '$(REAL_OUTPUT_DIR)' '$(APPLICATION_QUERY_OUTPUT_DIR)'\n"
            )
            def run(target, *overrides, environment=None):
                import os
                env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "INDEPENDENT_OUTPUT_DIR", "REAL_OUTPUT_DIR", "APPLICATION_QUERY_OUTPUT_DIR")}
                env.update(environment or {})
                return subprocess.run(["make", "--no-print-directory", target, *overrides], cwd=root, env=env, capture_output=True, text=True, check=True).stdout.splitlines()
            closure = root / "experiments/outputs/independent_benchmarks_closure"
            (closure / "regime_map").mkdir(parents=True)
            (closure / "benchmark_manifest.json").write_text("{}")
            (closure / "regime_map/run_manifest.json").write_text("{}")
            for target in ("paper-artifacts", "test-integration"):
                self.assertEqual(run(target)[:2], ["experiments/outputs/independent_benchmarks_closure", "experiments/outputs/real_dataset_closure"])
            self.assertEqual(run("bench-independent")[0], "experiments/outputs/independent_benchmarks")
            self.assertEqual(run("bench-real")[1], "experiments/outputs/real_dataset")
            self.assertEqual(run("paper-artifacts", "INDEPENDENT_OUTPUT_DIR=chosen", "REAL_OUTPUT_DIR=real_chosen")[:2], ["chosen", "real_chosen"])
            self.assertEqual(run("paper-artifacts", environment={"REAL_OUTPUT_DIR": "environment_real"})[1], "environment_real")
            canonical = root / "experiments/outputs/independent_benchmarks"
            (canonical / "regime_map").mkdir(parents=True)
            (canonical / "benchmark_manifest.json").write_text("{}")
            (canonical / "regime_map/run_manifest.json").write_text("{}")
            self.assertEqual(run("paper-artifacts")[:2], ["experiments/outputs/independent_benchmarks", "experiments/outputs/real_dataset"])

    def test_shared_source_never_redirects_to_another_run(self):
        from scripts.resolve_artifact_source import resolve
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = root / "engine"; engine.mkdir()
            source = root / "application_query"; source.mkdir()
            content = b'{"datasets": []}'
            (engine / "source_manifest.json").write_bytes(content)
            (source / "run_manifest.json").write_bytes(content)
            self.assertEqual(resolve(engine, Path("application_query"), root), Path("application_query"))
            other = root / "another_run"; other.mkdir()
            (other / "run_manifest.json").write_bytes(content)
            (source / "run_manifest.json").write_text("changed")
            with self.assertRaisesRegex(ValueError, "different application run"):
                resolve(engine, Path("application_query"), root)
            (engine / "source_manifest.json").unlink()
            self.assertEqual(resolve(engine, Path("application_query"), root), Path("application_query"))

    def test_consumers_use_one_application_source(self):
        makefile = (ROOT / "Makefile").read_text()
        for target in ("bench-tree", "bench-dbms", "tree-analysis", "dbms-analysis"):
            recipe = makefile.split("\n" + target + ":", 1)[1].split("\n\n", 1)[0]
            self.assertIn("$(APPLICATION_QUERY_OUTPUT_DIR)", recipe)
        self.assertNotIn("TREE_SOURCE_ROOT", makefile)
        self.assertNotIn("DBMS_SOURCE_ROOT", makefile)


class ArchiveResultsTest(unittest.TestCase):
    def test_archive_stays_in_repository_and_excludes_previous_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "scripts").mkdir(parents=True)
            script = root / "scripts/archive_results.py"
            script.write_bytes((ROOT / "scripts/archive_results.py").read_bytes())
            (root / "Makefile").write_text("fixture")
            (root / "backups").mkdir()
            (root / "backups/previous.tar.gz").write_text("previous backup")
            result = subprocess.run([sys.executable, str(script)], cwd=root,
                                    capture_output=True, text=True, check=True)
            archive = Path(result.stdout.strip())
            self.assertEqual(archive.parent, root / "backups/sources")
            expected_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(archive.with_suffix(".gz.sha256").read_text().split()[0], expected_hash)
            with tarfile.open(archive) as saved:
                self.assertIn("Makefile", saved.getnames())
                self.assertFalse(any(name.startswith("backups") for name in saved.getnames()))
            rejected = root.parent / "external"
            result = subprocess.run([sys.executable, str(script), "--output-dir", str(rejected)],
                                    cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(rejected.exists())


class MakefileTestCoverageTest(unittest.TestCase):
    """Coverage gates for Makefile test aggregators."""

    def test_aggregate_targets_preserve_transitive_validation(self) -> None:
        """Consolidated workflows keep CLI, adapter and artifact validation reachable."""
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        test_block = makefile.split("\ntest:", 1)[1].split("\ntest-cli:", 1)[0]
        self.assertIn("$(MAKE) test-cli", test_block)
        cgal_block = makefile.split("\ncgal-build:", 1)[1].split("\nreal-data:", 1)[0]
        self.assertIn("tests/integration/test_cgal_spatial_sort_adapter.py", cgal_block)
        bench_block = makefile.split("\nbench:", 1)[1].split("\nall-targets:", 1)[0]
        self.assertIn("$(MAKE) test-integration", bench_block)
        all_block = makefile.split("\nall-targets:", 1)[1].split("\ndocker-image:", 1)[
            0
        ]
        for target in ("test", "repro-smoke", "bench"):
            self.assertIn("$(MAKE) " + target, all_block)

    def test_run_all_tests_default_presets_match_cmake_test_presets(self) -> None:
        """The multi-preset wrapper remains aligned with CMakePresets.json."""
        presets = json.loads((ROOT / "CMakePresets.json").read_text(encoding="utf-8"))
        cmake_test_presets = [
            item["name"]
            for item in presets["testPresets"]
            if not item.get("hidden", False)
        ]
        script = (ROOT / "scripts/run_all_tests.sh").read_text(encoding="utf-8")
        for preset in cmake_test_presets:
            self.assertIn(f"  {preset}\n", script)
        self.assertIn("CTEST_EXCLUDE_REGEX:=paper_artifacts_python", script)

    def test_single_preset_runner_honors_ctest_exclude_regex(self) -> None:
        """scripts/test.sh can skip artifact-bound CTest buckets by regex."""
        script = (ROOT / "scripts/test.sh").read_text(encoding="utf-8")
        self.assertIn("CTEST_EXCLUDE_REGEX", script)
        self.assertIn("ctest_args+=(-E", script)

    def test_format_script_falls_back_when_git_lists_no_sources(self) -> None:
        """format.sh does not depend solely on tracked-file metadata."""
        script = (ROOT / "scripts/format.sh").read_text(encoding="utf-8")
        self.assertIn("git ls-files", script)
        self.assertIn("find include src", script)
        self.assertIn('if [ "${#cxx_files[@]}" -eq 0 ]', script)


if __name__ == "__main__":
    unittest.main()
