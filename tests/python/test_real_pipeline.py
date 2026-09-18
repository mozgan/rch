"""Unit tests for Real download/convert/runner/analysis helpers"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import struct
import tarfile
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import yaml

from analysis.scripts.make_real_tables import (
    directional_h1,
    latex_escape,
    make_real_tables,
    read_rows,
    table_rows,
)
from experiments.runners.run_real_datasets import (
    RealCase,
    bbox_diagonal,
    case_stem,
    expand_cases,
    load_algorithm_configs,
    load_manifest_datasets,
    load_refinement_modes,
    output_row,
    run_real_datasets,
    run_ordering as run_real_ordering,
    sampled_indices,
    sampled_l1_locality,
    sampled_l2_locality,
    sampled_recall_at_k_window,
)
from experiments.runners.run_matrix import PerfCounters
from scripts.convert_dataset import (
    bounds,
    convert_manifest,
    parse_ply_header,
    read_ply_points,
)
from scripts.download_dataset import (
    download_manifest,
    ensure_dataset,
    load_manifest,
    selected_datasets,
)
from scripts.create_demo_dataset import (
    DEMO_REAL_DATASETS,
    DEMO_TIMING_REPEATS,
    all_algorithm_ids,
    all_bit_rules,
    write_real_runlist,
    write_synthetic_runlist,
)


def sha256(data: bytes) -> str:
    """Return fixture SHA-256 for manifest tests."""
    return hashlib.sha256(data).hexdigest()


class RealDownloadTest(unittest.TestCase):
    """Checksum and dataset-selection tests for the Real downloader."""

    def test_file_url_download_and_checksum(self) -> None:
        """file:// fixtures exercise downloader logic without network."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            source.write_bytes(b"dataset-bytes")
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "fixture",
                                "url": f"file://{source}",
                                "filename": "fixture.bin",
                                "sha256": sha256(b"dataset-bytes"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            verified = download_manifest(
                Namespace(
                    manifest=manifest,
                    raw_dir=root / "raw",
                    dataset=["fixture"],
                    force=False,
                )
            )
            self.assertEqual(len(verified), 1)
            self.assertEqual(verified[0].read_bytes(), b"dataset-bytes")

    def test_checksum_mismatch_fails_closed(self) -> None:
        """Incorrect checksums delete the bad target and raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            source.write_bytes(b"bad")
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "fixture",
                                "url": f"file://{source}",
                                "filename": "fixture.bin",
                                "sha256": sha256(b"good"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                download_manifest(
                    Namespace(
                        manifest=manifest, raw_dir=root / "raw", dataset=[], force=True
                    )
                )


class RealConvertTest(unittest.TestCase):
    """PLY parsing and archive conversion edge cases."""

    def test_ascii_ply_with_extra_properties(self) -> None:
        """ASCII PLY keeps \(x,y,z\) and ignores additional vertex properties."""
        data = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 2\n"
            b"property float x\nproperty float y\nproperty float z\nproperty float confidence\n"
            b"end_header\n"
            b"1 2 3 0.5\n4 5 6 0.7\n"
        )
        points, header = read_ply_points(data)
        self.assertEqual(header.fmt, "ascii")
        self.assertEqual(points, [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

    def test_binary_big_endian_ply(self) -> None:
        """Binary big-endian PLY is parsed for Armadillo-style sources."""
        header = (
            b"ply\nformat binary_big_endian 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
        )
        data = header + struct.pack(">fff", 1.25, -2.5, 3.75)
        points, parsed = read_ply_points(data)
        self.assertEqual(parsed.fmt, "binary_big_endian")
        self.assertEqual(points, [(1.25, -2.5, 3.75)])

    def test_manifest_tar_and_gzip_conversion(self) -> None:
        """Converter handles tar.gz and gz archive entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            processed = root / "processed"
            ascii_ply = (
                b"ply\nformat ascii 1.0\n"
                b"element vertex 1\n"
                b"property float x\nproperty float y\nproperty float z\n"
                b"end_header\n"
                b"1 2 3\n"
            )
            tar_path = raw / "a.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                info = tarfile.TarInfo("inner/a.ply")
                info.size = len(ascii_ply)
                tar.addfile(info, io.BytesIO(ascii_ply))
            gz_path = raw / "b.ply.gz"
            with gzip.open(gz_path, "wb") as handle:
                handle.write(ascii_ply)
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "a",
                                "filename": "a.tar.gz",
                                "sha256": "not-used-by-converter",
                                "archive_type": "tar.gz",
                                "inner_path": "inner/a.ply",
                                "expected_vertices": 1,
                            },
                            {
                                "id": "b",
                                "filename": "b.ply.gz",
                                "sha256": "not-used-by-converter",
                                "archive_type": "gz",
                                "inner_path": "b.ply",
                                "expected_vertices": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            outputs = convert_manifest(
                Namespace(
                    manifest=manifest, raw_dir=raw, processed_dir=processed, dataset=[]
                )
            )
            self.assertEqual(len(outputs), 2)
            for output in outputs:
                self.assertTrue(output.exists())
                metadata = json.loads(
                    output.with_suffix(".metadata.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metadata["vertex_count"], 1)


class RealAnalysisTest(unittest.TestCase):
    """Directional H1 and table-generation tests."""

    def test_directional_h1_passes_only_when_a6_is_lower(self) -> None:
        """A6 must have lower MIAD than A3 on each dataset."""
        rows = [
            {
                "dataset_id": "bunny",
                "algorithm_id": "A3_isotropic_hilbert",
                "miad": 2.0,
            },
            {"dataset_id": "bunny", "algorithm_id": "A6_rch", "miad": 1.0},
            {
                "dataset_id": "armadillo",
                "algorithm_id": "A3_isotropic_hilbert",
                "miad": 3.0,
            },
            {"dataset_id": "armadillo", "algorithm_id": "A6_rch", "miad": 2.0},
        ]
        self.assertEqual(directional_h1(rows)["outcome"], "confirmed")
        self.assertTrue(directional_h1(rows)["passed"])
        rows[-1]["miad"] = 4.0
        failed = directional_h1(rows)
        self.assertEqual(failed["outcome"], "failed")
        self.assertFalse(failed["passed"])

    def test_read_rows_rejects_non_finite_numeric_cells(self) -> None:
        """Real analysis fails closed on present NaN/Inf metric cells."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "table_2_dataset_summary.csv").write_text(
                "runlist,dataset_id,algorithm_id,point_count,miad,normalized_miad\n"
                "table_2_dataset_summary,bunny,A6_rch,2,inf,0.1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-finite numeric field"):
                read_rows(root)

    def test_make_real_tables_writes_outputs(self) -> None:
        """Table and stats files are produced from a minimal Real CSV."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            tables = root / "tables"
            stats = root / "stats"
            results.mkdir()
            (results / "table_2_dataset_summary.csv").write_text(
                "\n".join(
                    [
                        "runlist,dataset_id,dataset_label,expected_vertices,algorithm_id,method,bit_rule,bit_allocator,point_count,sort_seconds,output_hash,bits_axis,robust_fallback_used,miad,normalized_miad",
                        "table_2_dataset_summary,bunny,Bunny,2,A3_isotropic_hilbert,isotropic_hilbert,C2,occupancy,2,0.1,h,10 10 10,false,2.0,0.2",
                        "table_2_dataset_summary,bunny,Bunny,2,A6_rch,rch,C2,occupancy,2,0.2,h,12 9 9,false,1.0,0.1",
                        "table_2_dataset_summary,armadillo,Armadillo,2,A3_isotropic_hilbert,isotropic_hilbert,C2,occupancy,2,0.1,h,10 10 10,false,3.0,0.3",
                        "table_2_dataset_summary,armadillo,Armadillo,2,A6_rch,rch,C2,occupancy,2,0.2,h,12 9 9,false,2.0,0.2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary = make_real_tables(
                Namespace(
                    results_dir=results,
                    tables_dir=tables,
                    stats_dir=stats,
                    require_h1=True,
                )
            )
            self.assertTrue(summary["definition_of_done_passed"])
            self.assertTrue((tables / "table_real_dataset_summary.tex").exists())
            self.assertTrue((tables / "table_real_dataset_summary.csv").exists())
            self.assertTrue((tables / "table_real_dataset_summary.json").exists())
            self.assertTrue(
                (tables / "table_real_directional_h1_comparisons.csv").exists()
            )
            self.assertIn("table_real_dataset_summary.tex", summary["tables"])
            self.assertTrue((stats / "real_statistics.json").exists())


class RealDownloadEdgeTest(unittest.TestCase):
    """Additional edge-case coverage for the Real downloader."""

    def test_load_manifest_rejects_non_mapping(self) -> None:
        """A YAML list at the root fails the mapping precondition."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.yml"
            path.write_text("- a\n- b\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_load_manifest_requires_dataset_list(self) -> None:
        """A mapping without a 'datasets' list fails closed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_datasets.yml"
            path.write_text("schema: x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_selected_datasets_filters_and_reports_missing(self) -> None:
        """Unknown dataset ids are reported via ValueError."""
        manifest = {"datasets": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(
            [item["id"] for item in selected_datasets(manifest, None)], ["a", "b"]
        )
        self.assertEqual(
            [item["id"] for item in selected_datasets(manifest, {"a"})], ["a"]
        )
        with self.assertRaises(ValueError):
            selected_datasets(manifest, {"a", "missing"})

    def test_ensure_dataset_reuses_cached_archive_without_redownload(self) -> None:
        """Cache-hit path skips the download step entirely."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_dir = root / "raw"
            target_dir.mkdir()
            archive = target_dir / "fixture.bin"
            archive.write_bytes(b"cached")
            digest = hashlib.sha256(b"cached").hexdigest()
            dataset = {
                "id": "fixture",
                "url": "file:///does/not/exist",  # would fail if hit
                "filename": "fixture.bin",
                "sha256": digest,
            }
            self.assertEqual(ensure_dataset(dataset, target_dir, force=False), archive)


class RealConvertEdgeTest(unittest.TestCase):
    """Additional edge-case coverage for the Real PLY converter."""

    def test_parse_ply_header_rejects_missing_end_marker(self) -> None:
        """Header without 'end_header' is rejected."""
        with self.assertRaises(ValueError):
            parse_ply_header(b"ply\nformat ascii 1.0\nelement vertex 1\n")

    def test_parse_ply_header_rejects_missing_xyz(self) -> None:
        """Vertex element must contain \(x,y,z\) scalar properties."""
        bad = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\n"  # missing z
            b"end_header\n"
        )
        with self.assertRaises(ValueError):
            parse_ply_header(bad)

    def test_parse_ply_header_rejects_list_vertex_property(self) -> None:
        """List-typed vertex properties are unsupported."""
        bad = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"property list uchar int neighbours\n"
            b"end_header\n"
        )
        with self.assertRaises(ValueError):
            parse_ply_header(bad)

    def test_binary_little_endian_ply_round_trip(self) -> None:
        """Binary little-endian PLY parses with the same \(x,y,z\) contract."""
        header = (
            b"ply\nformat binary_little_endian 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
        )
        data = header + struct.pack("<fff", 7.5, 2.5, -1.5)
        points, parsed = read_ply_points(data)
        self.assertEqual(parsed.fmt, "binary_little_endian")
        self.assertEqual(points, [(7.5, 2.5, -1.5)])

    def test_truncated_binary_ply_raises_value_error(self) -> None:
        """Binary PLY with insufficient bytes fails closed."""
        header = (
            b"ply\nformat binary_big_endian 1.0\n"
            b"element vertex 2\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
        )
        truncated = header + struct.pack(">fff", 1.0, 2.0, 3.0)  # only 1 vertex
        with self.assertRaises(ValueError):
            read_ply_points(truncated)

    def test_ascii_ply_rejects_non_finite_coordinate(self) -> None:
        """ASCII PLY with NaN coordinate fails closed."""
        bad = (
            b"ply\nformat ascii 1.0\n"
            b"element vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"end_header\n"
            b"1 2 nan\n"
        )
        with self.assertRaises(ValueError):
            read_ply_points(bad)

    def test_unsupported_archive_type_fails_closed(self) -> None:
        """convert_manifest rejects archive_type values outside tar.gz / gz."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            (raw / "x.zip").write_bytes(b"")
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "x",
                                "filename": "x.zip",
                                "sha256": "n/a",
                                "archive_type": "zip",
                                "inner_path": "x.ply",
                                "expected_vertices": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                convert_manifest(
                    Namespace(
                        manifest=manifest,
                        raw_dir=raw,
                        processed_dir=root / "out",
                        dataset=[],
                    )
                )

    def test_vertex_count_mismatch_fails_closed(self) -> None:
        """convert_dataset reports expected vs found vertex mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            ascii_ply = (
                b"ply\nformat ascii 1.0\n"
                b"element vertex 1\n"
                b"property float x\nproperty float y\nproperty float z\n"
                b"end_header\n"
                b"1 2 3\n"
            )
            gz_path = raw / "single.ply.gz"
            with gzip.open(gz_path, "wb") as handle:
                handle.write(ascii_ply)
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "single",
                                "filename": "single.ply.gz",
                                "sha256": "n/a",
                                "archive_type": "gz",
                                "inner_path": "single.ply",
                                "expected_vertices": 5,  # intentionally wrong
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                convert_manifest(
                    Namespace(
                        manifest=manifest,
                        raw_dir=raw,
                        processed_dir=root / "out",
                        dataset=[],
                    )
                )

    def test_bounds_handles_empty_input(self) -> None:
        """bounds([]) returns origin tuples (defensive)."""
        lo, hi = bounds([])
        self.assertEqual(lo, (0.0, 0.0, 0.0))
        self.assertEqual(hi, (0.0, 0.0, 0.0))


class RealRealRunnerEdgeTest(unittest.TestCase):
    """Edge-case coverage for run_real_datasets.py helpers."""

    # C2_occupancy_floor10 was removed: its floor equals `equal_bits() = 10`, so it
    # emitted \(10/10/10\) and was byte-identical to C0_uniform.
    BIT_RULE_IDS = [
        "C0_uniform",
        "C1_monotone_half",
        "C2_occupancy_floor1",
        "C3_frame_core_occupancy",
        "C4_hybrid",
    ]
    BIT_ALLOCATORS = [
        "uniform",
        "monotone_half",
        "occupancy_floor1",
        "frame_core_occupancy",
        "hybrid_occupancy",
    ]
    ALGORITHM_IDS = [
        "A0_input",
        "A1_lexicographic",
        "A2_morton",
        "A3_isotropic_hilbert",
        "A4_compact_hilbert_aabb",
        "A5_pca_compact_hilbert",
        "A5b_robust_frame_morton",
        "A6_rch",
        "A6_rch_b2_mrcd",
        "A6_rch_b3_ogk",
        "A7_cgal_spatial_sort",
    ]

    def test_bbox_diagonal_zero_for_empty_cloud(self) -> None:
        """Empty cloud ⇒ 0.0 (defensive)."""
        self.assertEqual(bbox_diagonal([]), 0.0)

    def test_real_config_loaders_reject_duplicate_ids(self) -> None:
        """Duplicate algorithm and dataset ids fail closed before matrix execution."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            algorithm_dir = root / "algorithms"
            algorithm_dir.mkdir()
            (algorithm_dir / "a.yaml").write_text(
                "id: A\nmethod: input\n", encoding="utf-8"
            )
            (algorithm_dir / "b.yaml").write_text(
                "id: A\nmethod: morton\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate algorithm config id"):
                load_algorithm_configs(algorithm_dir)

            manifest = root / "manifest.yml"
            manifest.write_text(
                "datasets:\n"
                "  - id: fixture\n"
                "  - id: fixture\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate manifest dataset id"):
                load_manifest_datasets(manifest)

    def test_real_runlist_covers_declared_c_axis(self) -> None:
        """table_2_dataset_summary carries the same declared C axis."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "experiments/runlists/table_2_dataset_summary.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            runlist = yaml.safe_load(handle)

        self.assertEqual(
            [rule["id"] for rule in runlist["bit_rules"]], self.BIT_RULE_IDS
        )
        self.assertEqual(
            [rule["bit_allocator"] for rule in runlist["bit_rules"]],
            self.BIT_ALLOCATORS,
        )

    def test_real_runlist_is_clean_only_on_d_axis(self) -> None:
        """Real benchmarks do not add synthetic D-axis outliers."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "experiments/runlists/table_2_dataset_summary.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            runlist = yaml.safe_load(handle)

        self.assertEqual(runlist["contamination_ids"], ["D0"])

    def test_real_runlist_includes_a7_for_e3_e4_next_bench(self) -> None:
        """The next real benchmark run includes A7 and robust-frame variants."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "experiments/runlists/table_2_dataset_summary.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            runlist = yaml.safe_load(handle)

        for algorithm_id in (
            "A6_rch",
            "A6_rch_b2_mrcd",
            "A6_rch_b3_ogk",
            "A7_cgal_spatial_sort",
        ):
            self.assertIn(algorithm_id, runlist["algorithm_ids"])
        self.assertEqual(runlist["geometry_ids"]["stanford_bunny"], "E3")
        self.assertEqual(runlist["geometry_ids"]["stanford_armadillo"], "E4")

    def test_demo_runlist_generator_uses_canonical_algorithm_and_c_axis(self) -> None:
        """bench-demo helper metadata is sourced from the canonical runlists."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "experiments/runlists/table_3_locality.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            canonical = yaml.safe_load(handle)

        self.assertEqual(all_algorithm_ids(), self.ALGORITHM_IDS)
        self.assertEqual(all_algorithm_ids(), canonical["algorithm_ids"])
        self.assertEqual([rule["id"] for rule in all_bit_rules()], self.BIT_RULE_IDS)
        self.assertEqual(
            [rule["bit_allocator"] for rule in all_bit_rules()],
            self.BIT_ALLOCATORS,
        )
        self.assertEqual(all_bit_rules(), canonical["bit_rules"])

    def test_demo_synthetic_runlists_match_canonical_runlists(self) -> None:
        """Synthetic demo runlists match canonical YAML except timing repeats."""
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "table_3_locality",
                "table_4_outlier",
                "table_5_runtime",
            ):
                target = root / f"{name}.yaml"
                source = repo / "experiments/runlists" / f"{name}.yaml"
                write_synthetic_runlist(target, name)
                demo = yaml.safe_load(target.read_text(encoding="utf-8"))
                canonical = yaml.safe_load(source.read_text(encoding="utf-8"))
                if "timing_repeats" in canonical:
                    self.assertEqual(demo.pop("timing_repeats"), DEMO_TIMING_REPEATS)
                    canonical.pop("timing_repeats")
                self.assertEqual(demo, canonical)

    def test_demo_real_runlist_matches_canonical_matrix_fields(self) -> None:
        """Real demo runlist only swaps dataset sources; benchmark axes stay real."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "experiments/runlists/table_2_dataset_summary.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            canonical = yaml.safe_load(handle)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "table_2_dataset_summary.yaml"
            write_real_runlist(
                target,
                repo / "data/manifests/rch_demo.yml",
                repo / "data/processed/rch_demo",
            )
            demo = yaml.safe_load(target.read_text(encoding="utf-8"))

        for key in (
            "schema",
            "name",
            "algorithm_ids",
            "bit_rules",
            "contamination_ids",
            "seeds",
            "metrics",
        ):
            self.assertEqual(demo[key], canonical[key])
        self.assertEqual(demo["dataset_manifest"], "data/manifests/rch_demo.yml")
        self.assertEqual(demo["processed_dir"], "data/processed/rch_demo")
        self.assertEqual(
            [item["geometry_id"] for item in DEMO_REAL_DATASETS], ["E3", "E4"]
        )
        self.assertEqual(
            demo["geometry_ids"],
            {"rch_demo_bunny": "E3", "rch_demo_armadillo": "E4"},
        )

    def test_run_real_datasets_rejects_synthetic_contamination_levels(self) -> None:
        """The Real runner fails before ordering when a runlist requests D1-D4."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [{"id": "fixture", "expected_vertices": 0}],
                    }
                ),
                encoding="utf-8",
            )
            runlist = root / "runlist.yml"
            runlist.write_text(
                yaml.safe_dump(
                    {
                        "schema": "rch.real_runlist.v1",
                        "name": "bad_real_d_axis",
                        "dataset_manifest": str(manifest),
                        "processed_dir": str(root / "processed"),
                        "dataset_ids": ["fixture"],
                        "geometry_ids": {"fixture": "E3"},
                        "algorithm_ids": ["A0_input"],
                        "bit_rules": [
                            {
                                "id": "C0_uniform",
                                "label": "C0 uniform",
                                "bit_allocator": "uniform",
                                "uniform_bits": 10,
                                "min_axis_bits": 1,
                            }
                        ],
                        "contamination_ids": ["D3"],
                        "seeds": [0],
                        "metrics": ["miad"],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "real runlists must use only clean D0"):
                run_real_datasets(
                    Namespace(
                        runlist=runlist,
                        output_dir=root / "out",
                        rch_order_bin=None,
                        cgal_adapter_bin=None,
                        block_read_probe_bin=None,
                        refinement="off",
                        max_runs=None,
                        exclude_external_baselines=False,
                    )
                )

    def test_make_bench_real_keeps_external_baselines_enabled(self) -> None:
        """Makefile bench-real must not filter A7 out of the real matrix."""
        repo = Path(__file__).resolve().parents[2]
        makefile = (repo / "Makefile").read_text(encoding="utf-8")
        start = makefile.index("bench-real:")
        end = makefile.index("\ndemo-data:", start)
        bench_real = makefile[start:end]

        self.assertIn("--cgal-adapter-bin $(CGAL_ADAPTER_BIN)", bench_real)
        self.assertNotIn("--sampled-metric-size", bench_real)
        self.assertNotIn("--exclude-external-baselines", bench_real)

    def test_make_bench_demo_routes_a7_through_cgal_adapter(self) -> None:
        """bench-demo uses the real CGAL adapter path for synthetic, real, and appendix."""
        repo = Path(__file__).resolve().parents[2]
        makefile = (repo / "Makefile").read_text(encoding="utf-8")
        synthetic_start = makefile.index("bench-demo-synthetic:")
        real_start = makefile.index("\nbench-demo-real:", synthetic_start)
        appendix_start = makefile.index("\ncgal-demo-appendix:", real_start)
        paper_start = makefile.index("\npaper-artifacts-demo:", appendix_start)
        synthetic_block = makefile[synthetic_start:real_start]
        real_block = makefile[real_start:appendix_start]
        appendix_block = makefile[appendix_start:paper_start]

        self.assertIn(
            "bench-demo-synthetic: bench-cpp cgal-adapter-bin demo-data",
            synthetic_block,
        )
        self.assertIn(
            "bench-demo-real: bench-cpp cgal-adapter-bin demo-data",
            real_block,
        )
        self.assertIn(
            "cgal-demo-appendix: cgal-adapter-bin demo-data",
            appendix_block,
        )
        self.assertIn("--cgal-adapter-bin $(CGAL_ADAPTER_BIN)", synthetic_block)
        self.assertIn("--cgal-adapter-bin $(CGAL_ADAPTER_BIN)", real_block)
        self.assertNotIn("--sampled-metric-size", real_block)
        self.assertNotIn("--exclude-external-baselines", real_block)
        self.assertIn("--dataset-catalog $(DEMO_REAL_CATALOG)", makefile)
        self.assertIn("demo-determinism-log", makefile)
        self.assertIn(
            "paper-artifacts-demo: bench-demo-synthetic bench-demo-real cgal-demo-appendix",
            makefile,
        )

    def test_run_real_datasets_routes_a7_through_cgal_adapter_for_ply_clean_case(
        self,
    ) -> None:
        """A7 real clean-PLY cells are normalized to CSV before adapter execution."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            (processed / "fixture.ply").write_text(
                "ply\n"
                "format ascii 1.0\n"
                "element vertex 2\n"
                "property float x\n"
                "property float y\n"
                "property float z\n"
                "end_header\n"
                "0 0 0\n"
                "1 0 0\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.yml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "schema": "test",
                        "datasets": [
                            {
                                "id": "fixture",
                                "label": "Fixture",
                                "expected_vertices": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            runlist = root / "runlist.yml"
            runlist.write_text(
                yaml.safe_dump(
                    {
                        "schema": "rch.real_runlist.v1",
                        "name": "table_2_dataset_summary",
                        "dataset_manifest": str(manifest),
                        "processed_dir": str(processed),
                        "dataset_ids": ["fixture"],
                        "geometry_ids": {"fixture": "E3"},
                        "algorithm_ids": ["A7_cgal_spatial_sort"],
                        "bit_rules": [
                            {
                                "id": "C3_frame_core_occupancy",
                                "label": "C2 occupancy floor10",
                                "bit_allocator": "frame_core_occupancy",
                                "uniform_bits": 10,
                                "min_axis_bits": 1,
                            }
                        ],
                        "contamination_ids": ["D0"],
                        "seeds": [0],
                        "metrics": ["miad", "recall_8_64_sampled", "sort_seconds"],
                    }
                ),
                encoding="utf-8",
            )
            fake_adapter = root / "fake_cgal.py"
            adapter_input = root / "adapter_input.txt"
            fake_adapter.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        f"pathlib.Path({str(adapter_input)!r}).write_text(args['--input'])",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n1,1,0\\n')",
                        "metadata = {",
                        "    'schema': 'rch.cgal_adapter.metadata.v1',",
                        "    'cgal_version': 'test-cgal',",
                        "    'cgal_version_nr': 123,",
                        "    'cgal_git_hash': 'test-hash',",
                        "    'spatial_sort_dimension': 3,",
                        "    'spatial_sort_policy': args['--policy'],",
                        "    'threshold_hilbert': 8,",
                        "    'threshold_multiscale': 64,",
                        "    'ratio': 0.125,",
                        "}",
                        "pathlib.Path(args['--metadata-output']).write_text(json.dumps(metadata) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_adapter.chmod(0o755)
            fake_rch = root / "fake_rch_order"
            fake_rch.write_text("# unused for A7-only test\n", encoding="utf-8")

            results_path = run_real_datasets(
                Namespace(
                    runlist=runlist,
                    output_dir=root / "out",
                    rch_order_bin=fake_rch,
                    cgal_adapter_bin=fake_adapter,
                    block_read_probe_bin=None,
                    refinement="off",
                    max_runs=None,
                    exclude_external_baselines=False,
                )
            )

            with results_path.open("r", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["algorithm_id"], "A7_cgal_spatial_sort")
            self.assertEqual(row["geometry_id"], "E3")
            self.assertEqual(row["method"], "external_cgal_spatial_sort")
            self.assertEqual(row["frame_estimator"], "none")
            self.assertEqual(row["refinement"], "external")
            self.assertEqual(row["bits_axis"], "0 0 0")
            self.assertTrue(row["sort_seconds"])
            self.assertEqual(row["recall_8_64_sampled"], "1.0")
            self.assertEqual(Path(adapter_input.read_text()).suffix, ".csv")

    def test_bbox_diagonal_matches_known_axis_aligned_box(self) -> None:
        """For corners (0,0,0) and (3,4,0) diagonal = 5."""
        self.assertAlmostEqual(bbox_diagonal([(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]), 5.0)

    def test_case_stem_is_filesystem_safe(self) -> None:
        """case_stem joins fields with double-underscore; no slashes/spaces."""
        case = RealCase(
            dataset={"id": "stanford_bunny"},
            geometry_id="E3",
            algorithm={"id": "A6_rch"},
            bit_rule={"id": "C3_frame_core_occupancy"},
            contamination={"id": "D1"},
            seed=3,
        )
        stem = case_stem(case)
        self.assertEqual(stem, "stanford_bunny__A6_rch__C3_frame_core_occupancy__D1__s3")
        self.assertNotIn("/", stem)
        self.assertNotIn(" ", stem)

    def test_expand_cases_rejects_missing_bit_rules(self) -> None:
        """Empty bit_rules fails closed."""
        with self.assertRaises(ValueError):
            expand_cases(
                {"dataset_ids": ["d"], "algorithm_ids": ["A"], "bit_rules": []},
                {"d": {"id": "d"}},
                {"A": {"id": "A"}},
            )

    def test_output_row_filters_metrics(self) -> None:
        """Only requested metrics populate the row; others are blank strings."""
        case = RealCase(
            dataset={"id": "d", "label": "D", "expected_vertices": 2},
            geometry_id="E3",
            algorithm={"id": "A6_rch", "method": "rch"},
            bit_rule={
                "id": "C3_frame_core_occupancy",
                "bit_allocator": "frame_core_occupancy",
            },
            contamination={"id": "D0", "mode": "clean"},
            seed=0,
        )
        manifest = {
            "hash": "h",
            "bits_axis": [10, 10, 10],
            "robust_fallback_used": False,
        }
        row = output_row(
            case,
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            [0, 1],
            manifest,
            sort_seconds=0.5,
            metrics={"miad"},
            clean_count=2,
        )
        self.assertIsInstance(row["miad"], float)
        self.assertEqual(row["sort_seconds"], "")
        self.assertEqual(row["normalized_miad"], "")

    def test_output_row_populates_real_metric_surface_for_small_clouds(self) -> None:
        """Real can emit M1/M2/M4/M5/M7/M8/M9 when metrics request them."""
        case = RealCase(
            dataset={"id": "d", "label": "D", "expected_vertices": 3},
            geometry_id="E3",
            algorithm={"id": "A6_rch", "method": "rch"},
            bit_rule={
                "id": "C3_frame_core_occupancy",
                "bit_allocator": "frame_core_occupancy",
            },
            contamination={"id": "D0", "mode": "clean"},
            seed=0,
        )
        manifest = {
            "hash": "h",
            "bits_axis": [10, 10, 10],
            "robust_fallback_used": False,
            "peak_rss_kb": 2048,
            "frame_axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "frame_estimator": "det_mcd",
        }
        metrics = {
            "miad",
            "normalized_miad",
            "m1_l1_locality",
            "m1_l1_sampled",
            "m1_l2_locality",
            "m1_l2_sampled",
            "recall_8_64",
            "recall_8_64_sampled",
            "kendall_tau_clean",
            "frame_angle_rad",
            "peak_rss_kb",
            "cache_references",
            "cache_misses",
            "cache_miss_rate",
            "perf_status",
            "block_read_mean",
            "block_read_p95",
            "sort_seconds",
        }
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        row = output_row(
            case,
            points,
            [0, 1, 2],
            manifest,
            sort_seconds=0.5,
            metrics=metrics,
            clean_count=3,
            perf_counters=PerfCounters(
                status="ok", cache_references=100, cache_misses=5
            ),
            clean_order=[0, 1, 2],
            clean_frame_axes=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        )

        self.assertEqual(row["m1_l1_status"], "exact")
        self.assertEqual(row["m1_l1_sampled_status"], "exact")
        self.assertEqual(row["m1_l2_status"], "exact")
        self.assertEqual(row["m1_l2_sampled_status"], "exact")
        self.assertEqual(row["recall_8_64_status"], "exact")
        self.assertEqual(row["recall_8_64_sampled_status"], "exact")
        self.assertIsInstance(row["m1_l1_locality"], float)
        self.assertIsInstance(row["m1_l1_sampled"], float)
        self.assertIsInstance(row["m1_l2_locality"], float)
        self.assertIsInstance(row["m1_l2_sampled"], float)
        # \(L_1\) (max) is always \(\ge L_2\) (min) over the same pairs.
        self.assertGreaterEqual(row["m1_l1_locality"], row["m1_l2_locality"])
        self.assertEqual(row["recall_8_64"], 1.0)
        self.assertEqual(row["recall_8_64_sampled"], 1.0)
        self.assertEqual(row["kendall_tau_clean"], 1.0)
        self.assertEqual(row["frame_angle_rad"], 0.0)
        self.assertEqual(row["peak_rss_kb"], 2048.0)
        self.assertEqual(row["cache_references"], 100)
        self.assertEqual(row["cache_misses"], 5)
        self.assertAlmostEqual(row["cache_miss_rate"], 0.05)
        self.assertEqual(row["perf_status"], "ok")
        self.assertEqual(row["block_read_p95"], 2.0)

    def test_output_row_populates_real_canonical_metrics_with_explicit_sample_proxy(
        self,
    ) -> None:
        """Explicit samples keep canonical metric columns non-empty with proxy status."""
        case = RealCase(
            dataset={"id": "d", "label": "D", "expected_vertices": 5},
            geometry_id="E3",
            algorithm={"id": "A6_rch", "method": "rch"},
            bit_rule={
                "id": "C3_frame_core_occupancy",
                "bit_allocator": "frame_core_occupancy",
            },
            contamination={"id": "D0", "mode": "clean"},
            seed=0,
        )
        manifest = {
            "hash": "h",
            "bits_axis": [10, 10, 10],
            "robust_fallback_used": False,
            "frame_estimator": "det_mcd",
        }
        points = [(float(index), 0.0, 0.0) for index in range(5)]
        metrics = {
            "m1_l1_locality",
            "m1_l1_sampled",
            "m1_l2_locality",
            "m1_l2_sampled",
            "recall_8_64",
            "recall_8_64_sampled",
        }
        row = output_row(
            case,
            points,
            [0, 1, 2, 3, 4],
            manifest,
            sort_seconds=0.0,
            metrics=metrics,
            clean_count=5,
            sampled_metric_size=3,
        )

        self.assertEqual(row["m1_l1_status"], "deterministic_sampled_proxy")
        self.assertEqual(
            row["m1_l1_sampled_status"], "deterministic_sampled_proxy"
        )
        self.assertEqual(row["m1_l2_status"], "deterministic_sampled_proxy")
        self.assertEqual(
            row["m1_l2_sampled_status"], "deterministic_sampled_proxy"
        )
        self.assertEqual(row["recall_8_64_status"], "deterministic_sampled_proxy")
        self.assertEqual(
            row["recall_8_64_sampled_status"], "deterministic_sampled_proxy"
        )
        self.assertEqual(row["m1_l1_locality"], row["m1_l1_sampled"])
        self.assertEqual(row["m1_l2_locality"], row["m1_l2_sampled"])
        self.assertEqual(row["recall_8_64"], row["recall_8_64_sampled"])
        self.assertNotEqual(row["m1_l1_locality"], "")
        self.assertNotEqual(row["m1_l2_locality"], "")
        self.assertNotEqual(row["recall_8_64"], "")

    def test_sampled_real_metrics_are_deterministic_large_n_proxies(self) -> None:
        """Sampled M1/M2 helpers avoid claiming full-N exactness."""
        points = [(float(index), 0.0, 0.0) for index in range(10)]
        order = list(range(10))

        self.assertEqual(sampled_indices(10, 4), [0, 3, 6, 9])
        first_m1 = sampled_l1_locality(points, order, sample_size=4)
        second_m1 = sampled_l1_locality(points, order, sample_size=4)
        first_m1_l2 = sampled_l2_locality(points, order, sample_size=4)
        second_m1_l2 = sampled_l2_locality(points, order, sample_size=4)
        first_recall = sampled_recall_at_k_window(
            points, order, sample_size=4, k=2, window=4
        )
        second_recall = sampled_recall_at_k_window(
            points, order, sample_size=4, k=2, window=4
        )

        self.assertEqual(first_m1, second_m1)
        self.assertEqual(first_m1_l2, second_m1_l2)
        self.assertEqual(first_recall, second_recall)
        self.assertEqual(first_m1[1], 4)
        self.assertEqual(first_m1_l2[1], 4)
        # Sampled \(L_1\) (max) is an upper envelope of sampled \(L_2\) (min).
        self.assertGreaterEqual(first_m1[0], first_m1_l2[0])
        self.assertEqual(first_recall[1], 4)
        self.assertEqual(
            sampled_recall_at_k_window(points, order, sample_size=4, k=0, window=4),
            (1.0, 4),
        )

    def test_sampled_real_metrics_fail_closed_on_malformed_orders(self) -> None:
        """Sampled proxies return zero metric values for invalid permutations."""
        points = [(float(index), 0.0, 0.0) for index in range(5)]
        bad_order = [0, 1, 1, 3, 4]
        self.assertEqual(
            sampled_l1_locality(points, bad_order, sample_size=3), (0.0, 3)
        )
        self.assertEqual(
            sampled_l2_locality(points, bad_order, sample_size=3), (0.0, 3)
        )
        self.assertEqual(
            sampled_recall_at_k_window(points, bad_order, sample_size=3),
            (0.0, 3),
        )


class RealRefinementSweepTest(unittest.TestCase):
    """The R-axis refinement sweep config is the single declared mode source."""

    def test_refinement_sweep_pins_recorded_arms_and_default(self) -> None:
        """Recorded arms and default match the equal-treatment ablation protocol."""
        modes, default = load_refinement_modes()
        self.assertEqual(modes, ["off", "all"])
        self.assertEqual(default, "off")

    def test_load_refinement_modes_rejects_non_string_mode_id(self) -> None:
        """An unquoted YAML `off` parses as a boolean and must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refinement.yaml"
            path.write_text(
                "schema: rch.sweep.refinement.v1\n"
                'default_mode: "off"\n'
                "modes:\n"
                "  - id: off\n"
                "  - id: all\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_refinement_modes(path)

    def test_load_refinement_modes_rejects_default_outside_modes(self) -> None:
        """A default mode missing from the declared arms fails closed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refinement.yaml"
            path.write_text(
                "schema: rch.sweep.refinement.v1\n"
                "default_mode: bogus\n"
                "modes:\n"
                '  - id: "off"\n'
                "  - id: all\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_refinement_modes(path)

    def test_run_real_datasets_rejects_unknown_refinement_mode(self) -> None:
        """The runner facade fails closed before any runlist or dataset work."""
        with self.assertRaises(ValueError):
            run_real_datasets(Namespace(refinement="bogus"))

    def test_real_input_ordering_forces_refinement_off(self) -> None:
        """Real runner keeps the input-order control fixed under all arms."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_rch_order.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "manifest = pathlib.Path(args['--manifest'])",
                        "manifest.with_suffix("
                        "manifest.suffix + '.refinement'"
                        ").write_text(args['--refinement'])",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            case = RealCase(
                dataset={"id": "fixture"},
                geometry_id="E3",
                algorithm={"id": "A0_input", "method": "input"},
                bit_rule={"id": "C", "bit_allocator": "frame_core_occupancy"},
                contamination={"id": "D0", "mode": "clean"},
                seed=0,
            )
            points = root / "points.csv"
            order = root / "order.csv"
            manifest = root / "manifest.json"
            points.write_text("0,0,0\n", encoding="utf-8")

            run_real_ordering(fake, None, case, points, order, manifest, "all")

            self.assertEqual((root / "manifest.json.refinement").read_text(), "off")


class RealAnalysisEdgeTest(unittest.TestCase):
    """Edge-case coverage for make_real_tables.py helpers."""

    def test_directional_h1_with_only_one_dataset_fails(self) -> None:
        """Fewer than 2 datasets ⇒ passed=False."""
        rows = [
            {
                "dataset_id": "bunny",
                "algorithm_id": "A3_isotropic_hilbert",
                "miad": 2.0,
            },
            {"dataset_id": "bunny", "algorithm_id": "A6_rch", "miad": 1.0},
        ]
        h1 = directional_h1(rows)
        self.assertFalse(h1["passed"])
        self.assertEqual(h1["outcome"], "insufficient_data")
        self.assertEqual(len(h1["comparisons"]), 1)

    def test_directional_h1_skips_dataset_missing_a3(self) -> None:
        """A dataset without both A3 and A6 produces no comparison row."""
        rows = [
            {
                "dataset_id": "bunny",
                "algorithm_id": "A3_isotropic_hilbert",
                "miad": 2.0,
            },
            {"dataset_id": "bunny", "algorithm_id": "A6_rch", "miad": 1.0},
            {"dataset_id": "armadillo", "algorithm_id": "A6_rch", "miad": 0.5},
        ]
        h1 = directional_h1(rows)
        self.assertEqual(len(h1["comparisons"]), 1)
        self.assertEqual(h1["outcome"], "insufficient_data")
        self.assertFalse(h1["passed"])

    def test_latex_escape_handles_special_characters(self) -> None:
        """latex_escape escapes %, &, _, and \\."""
        self.assertEqual(latex_escape("a_b%c&d\\e"), "a\\_b\\%c\\&d\\textbackslash{}e")

    def test_table_rows_orders_by_dataset_then_algorithm(self) -> None:
        """Rows are sorted deterministically for paper-table reproducibility."""
        rows = [
            {
                "dataset_id": "z",
                "algorithm_id": "A6_rch",
                "point_count": 1,
                "bits_axis": "1 1 1",
                "miad": 1.0,
                "normalized_miad": 0.5,
                "sort_seconds": 0.1,
                "robust_fallback_used": "False",
            },
            {
                "dataset_id": "a",
                "algorithm_id": "A2_morton",
                "point_count": 1,
                "bits_axis": "1 1 1",
                "miad": 2.0,
                "normalized_miad": 1.0,
                "sort_seconds": 0.2,
                "robust_fallback_used": "False",
            },
        ]
        formatted = table_rows(rows)
        self.assertEqual([row["dataset_id"] for row in formatted], ["a", "z"])


if __name__ == "__main__":
    unittest.main()
