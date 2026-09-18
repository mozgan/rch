"""Unit tests for paper figure/table artifact generation"""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from collections import Counter
from pathlib import Path

import yaml

from analysis.scripts.make_paper_artifacts import (
    MAIN_COMPARISON_BIT_RULE,
    MAIN_METHOD_COMPARISON_SERIES,
    STABILITY_ALGORITHMS,
    STABILITY_COMPARISON_SERIES,
    latex_table,
    make_paper_artifacts,
    numeric,
    parse_bits_axis,
    read_csv_rows,
)

ROOT = Path(__file__).resolve().parents[2]

BIT_ALLOCATOR_BY_RULE = {
    "C0_uniform": "uniform",
    "C1_monotone_half": "monotone_half",
    "C2_occupancy_floor1": "occupancy_floor1",
    "C3_frame_core_occupancy": "frame_core_occupancy",
    "C4_hybrid": "hybrid_occupancy",
}


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def algorithm_bit_rule_count(runlist: dict) -> int:
    algorithms_dir = ROOT / "experiments/configs/algorithms"
    algorithms = {
        read_yaml(path)["id"]: read_yaml(path) for path in algorithms_dir.glob("*.yaml")
    }
    bit_rule_ids = {rule["id"] for rule in runlist["bit_rules"]}
    count = 0
    for algorithm_id in runlist["algorithm_ids"]:
        supported = algorithms[algorithm_id].get("supported_bit_rules")
        if isinstance(supported, list):
            count += len(bit_rule_ids & {str(item) for item in supported})
        else:
            count += len(bit_rule_ids)
    return count


def declared_bit_rule_ids(runlist: dict) -> set[str]:
    return {str(rule["id"]) for rule in runlist["bit_rules"]}


SYNTHETIC_HEADER = (
    "runlist,algorithm_id,method,bit_rule,bit_allocator,contamination_id,"
    "contamination_mode,geometry_id,point_count,clean_point_count,seed,"
    "frame_estimator,sort_seconds,output_hash,bits_axis,robust_fallback_used,miad,"
    "m1_l1_locality,l1_locality,m1_l2_locality,l2_locality,"
    "recall_8_64,peak_rss_kb,block_read_mean,block_read_p95,cache_references,cache_misses,"
    "cache_miss_rate,perf_status,kendall_tau_clean,frame_angle_rad"
)


def synthetic_row(
    runlist: str,
    algorithm: str,
    geometry: str,
    point_count: int,
    seed: int,
    *,
    contamination: str = "D0",
    sort_seconds: float = 0.01,
    bits_axis: str = "4 4 4",
    miad: float = 1.0,
    l2: str = "",
    l2_min: str = "",
    recall: str = "",
    peak_rss: str = "",
    block_mean: str = "",
    block_p95: str = "",
    cache_refs: str = "",
    cache_misses: str = "",
    cache_rate: str = "",
    perf_status: str = "",
    tau: str = "",
    frame_angle: str = "",
    frame_estimator: str = "none",
    bit_rule: str = "C3_frame_core_occupancy",
) -> str:
    """Return one CSV row compatible with Synthetic summary files."""
    bit_allocator = BIT_ALLOCATOR_BY_RULE.get(bit_rule, "hybrid_occupancy")
    return ",".join(
        [
            runlist,
            algorithm,
            algorithm.removeprefix("A6_"),
            bit_rule,
            bit_allocator,
            contamination,
            "clean" if contamination == "D0" else "uniform_bbox",
            geometry,
            str(point_count),
            str(point_count),
            str(seed),
            frame_estimator,
            str(sort_seconds),
            "hash",
            bits_axis,
            "False",
            str(miad),
            str(l2),
            str(l2),
            str(l2_min),
            str(l2_min),
            str(recall),
            str(peak_rss),
            str(block_mean),
            str(block_p95),
            str(cache_refs),
            str(cache_misses),
            str(cache_rate),
            str(perf_status),
            str(tau),
            str(frame_angle),
        ]
    )


class PaperArtifactHelpersTest(unittest.TestCase):
    """Small pure-helper tests."""

    def test_numeric_rejects_empty_and_non_finite(self) -> None:
        """numeric returns finite floats only."""
        self.assertEqual(numeric("1.25"), 1.25)
        self.assertIsNone(numeric(""))
        self.assertIsNone(numeric("nan"))
        self.assertIsNone(numeric("inf"))

    def test_read_csv_rows_rejects_non_finite_numeric_cells(self) -> None:
        """Paper artifact inputs fail closed on present NaN/Inf metric cells."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            path.write_text("runlist,point_count,miad\nx,2,nan\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite numeric field"):
                read_csv_rows(path)

    def test_parse_bits_axis_requires_three_nonnegative_ints(self) -> None:
        """bits_axis parser accepts exactly three nonnegative integers."""
        self.assertEqual(parse_bits_axis("8 7 5"), (8, 7, 5))
        self.assertIsNone(parse_bits_axis("8 7"))
        self.assertIsNone(parse_bits_axis("8 -1 5"))
        self.assertIsNone(parse_bits_axis("x y z"))

    def test_latex_table_escapes_special_characters(self) -> None:
        """Generated tables escape underscores and ampersands."""
        text = latex_table(
            [{"name": "a_b", "status": "A&B"}],
            ["name", "status"],
            "caption",
            "tab:test",
        )
        self.assertIn("a\\_b", text)
        self.assertIn("A\\&B", text)

    def test_contamination_strategy_keeps_b_axis_estimators_visible(self) -> None:
        """The contamination figure covers B0-B3 plus the A7 external baseline."""
        self.assertEqual(
            STABILITY_ALGORITHMS,
            (
                "A5_pca_compact_hilbert",
                "A6_rch",
                "A6_rch_b2_mrcd",
                "A6_rch_b3_ogk",
                "A7_cgal_spatial_sort",
            ),
        )
        self.assertEqual(
            STABILITY_COMPARISON_SERIES,
            tuple(
                (algorithm, MAIN_COMPARISON_BIT_RULE)
                for algorithm in STABILITY_ALGORITHMS
            ),
        )

    def test_main_result_figures_use_one_algorithm_ladder(self) -> None:
        """Main metric figures use the selected algorithm ladder, not all C-axis rows."""
        self.assertEqual(
            MAIN_METHOD_COMPARISON_SERIES,
            (
                ("A0_input", "C0_uniform"),
                ("A1_lexicographic", "C0_uniform"),
                ("A2_morton", "C3_frame_core_occupancy"),
                ("A3_isotropic_hilbert", "C3_frame_core_occupancy"),
                ("A4_compact_hilbert_aabb", "C3_frame_core_occupancy"),
                ("A5_pca_compact_hilbert", "C3_frame_core_occupancy"),
                ("A5b_robust_frame_morton", "C3_frame_core_occupancy"),
                ("A6_rch", "C3_frame_core_occupancy"),
                ("A7_cgal_spatial_sort", "C3_frame_core_occupancy"),
            ),
        )

    def test_rch_branch_uses_detmcd_style_wording(self) -> None:
        """Implementation-specific RCH text keeps the DetMCD-style qualifier."""
        required_paths = (
            ROOT / "include/rch/robust/det_mcd.hpp",
            ROOT / "paper/sections/00_abstract.tex",
            ROOT / "paper/sections/01_introduction.tex",
            ROOT / "paper/sections/05_methodology.tex",
            ROOT / "paper/sections/07_experimental_setup.tex",
            ROOT / "paper/sections/09_discussion.tex",
            ROOT / "paper/figures/fig_schema_method_pipeline.tex",
        )
        missing = [path for path in required_paths if not path.exists()]
        if missing:
            self.skipTest(
                "paper sources are not present in this checkout: "
                + ", ".join(str(path.relative_to(ROOT)) for path in missing)
            )
        for path in required_paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("DetMCD-style", text, path)

    def test_portability_and_permutation_limits_are_visible(self) -> None:
        """Boundary-sensitive reproducibility limits stay explicit."""
        required_paths = (
            ROOT / "paper/sections/05_methodology.tex",
            ROOT / "paper/sections/09_discussion.tex",
            ROOT / "include/rch/curves/quantization.hpp",
        )
        missing = [path for path in required_paths if not path.exists()]
        if missing:
            self.skipTest(
                "paper sources are not present in this checkout: "
                + ", ".join(str(path.relative_to(ROOT)) for path in missing)
            )
        methodology = (ROOT / "paper/sections/05_methodology.tex").read_text(
            encoding="utf-8"
        )
        discussion = (ROOT / "paper/sections/09_discussion.tex").read_text(
            encoding="utf-8"
        )
        quantization = (ROOT / "include/rch/curves/quantization.hpp").read_text(
            encoding="utf-8"
        )

        methodology_words = " ".join(methodology.split())
        discussion_words = " ".join(discussion.split())
        self.assertIn("not a universal floating-point theorem", methodology_words)
        self.assertIn("long double", quantization)
        self.assertIn("Boundary-adjacent", quantization)
        self.assertIn("Permutation-stability scope", discussion_words)
        self.assertIn("Exact-tie structured inputs", discussion_words)


class PaperArtifactEndToEndTest(unittest.TestCase):
    """End-to-end smoke tests for named paper artifacts."""

    def test_make_paper_artifacts_writes_all_expected_outputs(self) -> None:
        """A minimal Synthetic/Real/log fixture produces every paper artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            synthetic = root / "synthetic"
            real = root / "real"
            a7 = root / "a7"
            logs = root / "logs"
            figures = root / "figures"
            outputs = root / "outputs"
            tables = root / "tables"
            stats = root / "stats"
            dataset_catalog = root / "real_dataset_catalog.yml"
            synthetic.mkdir()
            real.mkdir()
            a7.mkdir()
            logs.mkdir()
            stats.mkdir()
            synthetic_primary = synthetic / "off"
            synthetic_all = synthetic / "all"
            real_primary = real / "off"
            real_all = real / "all"
            synthetic_primary.mkdir(parents=True)
            synthetic_all.mkdir()
            real_primary.mkdir(parents=True)
            real_all.mkdir()
            (outputs / "synthetic_refinement").mkdir(parents=True)
            (outputs / "synthetic_refinement" / "stale.csv").write_text(
                "stale\n", encoding="utf-8"
            )
            (outputs / "real_refinement").mkdir()
            (outputs / "real_refinement" / "stale.csv").write_text(
                "stale\n", encoding="utf-8"
            )

            (synthetic_primary / "table_3_locality.csv").write_text(
                "\n".join(
                    [
                        SYNTHETIC_HEADER,
                        synthetic_row(
                            "table_3_locality",
                            "A2_morton",
                            "E0",
                            384,
                            0,
                            miad=1.4,
                            l2="10",
                            recall="0.50",
                        ),
                        synthetic_row(
                            "table_3_locality",
                            "A3_isotropic_hilbert",
                            "E0",
                            384,
                            0,
                            miad=1.2,
                            l2="8",
                            recall="0.60",
                        ),
                        synthetic_row(
                            "table_3_locality",
                            "A6_rch",
                            "E0",
                            384,
                            0,
                            bits_axis="4 3 3",
                            miad=1.1,
                            l2="7",
                            recall="0.70",
                        ),
                        synthetic_row(
                            "table_3_locality",
                            "A2_morton",
                            "E1",
                            384,
                            0,
                            miad=1.8,
                            l2="20",
                            recall="0.40",
                        ),
                        synthetic_row(
                            "table_3_locality",
                            "A3_isotropic_hilbert",
                            "E1",
                            384,
                            0,
                            miad=1.6,
                            l2="18",
                            recall="0.50",
                        ),
                        synthetic_row(
                            "table_3_locality",
                            "A6_rch",
                            "E1",
                            384,
                            0,
                            bits_axis="5 2 2",
                            miad=1.3,
                            l2="14",
                            recall="0.65",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (synthetic_primary / "table_4_outlier.csv").write_text(
                "\n".join(
                    [
                        SYNTHETIC_HEADER,
                        synthetic_row(
                            "table_4_outlier",
                            "A5_pca_compact_hilbert",
                            "E1",
                            128,
                            0,
                            miad=2.0,
                            tau="0.8",
                        ),
                        synthetic_row(
                            "table_4_outlier",
                            "A6_rch",
                            "E1",
                            128,
                            0,
                            bits_axis="5 2 2",
                            miad=1.5,
                            tau="0.7",
                        ),
                        synthetic_row(
                            "table_4_outlier",
                            "A5_pca_compact_hilbert",
                            "E1",
                            128,
                            0,
                            contamination="D1",
                            miad=3.0,
                            tau="0.5",
                        ),
                        synthetic_row(
                            "table_4_outlier",
                            "A6_rch",
                            "E1",
                            128,
                            0,
                            contamination="D1",
                            bits_axis="5 2 2",
                            miad=2.5,
                            tau="0.6",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (synthetic_primary / "table_5_runtime.csv").write_text(
                "\n".join(
                    [
                        SYNTHETIC_HEADER,
                        synthetic_row(
                            "table_5_runtime",
                            "A2_morton",
                            "E0",
                            128,
                            0,
                            sort_seconds=0.01,
                            block_p95="3.0",
                            cache_rate="0.10",
                        ),
                        synthetic_row(
                            "table_5_runtime",
                            "A2_morton",
                            "E0",
                            256,
                            0,
                            sort_seconds=0.02,
                            block_p95="4.0",
                            cache_rate="0.11",
                        ),
                        synthetic_row(
                            "table_5_runtime",
                            "A3_isotropic_hilbert",
                            "E0",
                            128,
                            0,
                            sort_seconds=0.012,
                            block_p95="2.8",
                            cache_rate="0.08",
                        ),
                        synthetic_row(
                            "table_5_runtime",
                            "A3_isotropic_hilbert",
                            "E0",
                            256,
                            0,
                            sort_seconds=0.024,
                            block_p95="3.8",
                            cache_rate="0.09",
                        ),
                        synthetic_row(
                            "table_5_runtime",
                            "A6_rch",
                            "E0",
                            128,
                            0,
                            bits_axis="4 3 3",
                            sort_seconds=0.03,
                            block_p95="2.0",
                            cache_rate="0.05",
                        ),
                        synthetic_row(
                            "table_5_runtime",
                            "A6_rch",
                            "E0",
                            256,
                            0,
                            bits_axis="4 3 3",
                            sort_seconds=0.06,
                            block_p95="2.5",
                            cache_rate="0.06",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (synthetic_primary / "orders").mkdir()
            (synthetic_primary / "orders" / "synthetic_case.order.csv").write_text(
                "rank,raw_index,key\n0,0,1\n",
                encoding="utf-8",
            )
            (synthetic_all / "table_3_locality.csv").write_text(
                SYNTHETIC_HEADER
                + "\n"
                + synthetic_row(
                    "table_3_locality",
                    "A6_rch",
                    "E0",
                    384,
                    0,
                    bits_axis="4 3 3",
                    miad=1.0,
                    l2="7",
                    recall="0.7",
                )
                + "\n",
                encoding="utf-8",
            )
            (real_primary / "manifests").mkdir()
            (real_primary / "manifests" / "real_case.manifest.json").write_text(
                json.dumps({"status": "ok", "hash": "abc"}) + "\n",
                encoding="utf-8",
            )
            (real_primary / "refinement_note.json").write_text(
                json.dumps({"status": "ok", "mode": "off"}) + "\n",
                encoding="utf-8",
            )
            real_refinement_header = (
                "runlist,dataset_id,dataset_label,geometry_id,expected_vertices,"
                "algorithm_id,method,bit_rule,bit_allocator,point_count,"
                "clean_point_count,contamination_id,contamination_mode,seed,"
                "frame_estimator,refinement,sort_seconds,output_hash,bits_axis,"
                "robust_fallback_used,miad,normalized_miad,"
                "m1_l1_locality,m1_l1_status,m1_l1_sampled,"
                "m1_l1_sampled_status,m1_l2_locality,m1_l2_status,"
                "m1_l2_sampled,m1_l2_sampled_status,recall_8_64,"
                "recall_8_64_status,recall_8_64_sampled,"
                "recall_8_64_sampled_status"
            )
            (real_primary / "table_2_dataset_summary.csv").write_text(
                "\n".join(
                    [
                        real_refinement_header,
                        "table_2_dataset_summary,bunny,Bunny,E3,2,A6_rch,rch,"
                        "C3_frame_core_occupancy,frame_core_occupancy,2,2,D0,none,0,"
                        "det_mcd,off,0.1,h,5 4 3,False,2.0,0.2,"
                        "1.0,exact,1.0,exact,0.5,exact,0.5,exact,"
                        "0.25,exact,0.25,exact",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (real_all / "table_2_dataset_summary.csv").write_text(
                "\n".join(
                    [
                        real_refinement_header,
                        "table_2_dataset_summary,bunny,Bunny,E3,2,A6_rch,rch,"
                        "C3_frame_core_occupancy,frame_core_occupancy,2,2,D0,none,0,"
                        "det_mcd,all,0.1,h,5 4 3,False,1.5,0.15,"
                        "1.0,exact,1.0,exact,0.5,exact,0.5,exact,"
                        "0.25,exact,0.25,exact",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (a7 / "a7_cgal_spatial_sort.csv").write_text(
                "\n".join(
                    [
                        "algorithm_id,policy,point_count,order_path,permutation_hash,permutation",
                        "A7_cgal_spatial_sort,median,8,median.order.csv,abc,0 1 2 3 4 5 6 7",
                        "A7_cgal_spatial_sort,middle,8,middle.order.csv,def,0 2 1 3 4 5 6 7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (stats / "synthetic_statistics.json").write_text(
                json.dumps(
                    {
                        "hypotheses": [
                            {"hypothesis": "H1", "passed": True, "p_adj": 0.01},
                            {"hypothesis": "H2", "passed": True, "p_adj": 0.02},
                            {
                                "hypothesis": "H7_A7",
                                "passed": True,
                                "p_adj": 0.03,
                                "median_delta_rch_minus_baseline": -0.1,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (stats / "real_statistics.json").write_text(
                json.dumps(
                    {
                        "hypotheses": [
                            {
                                "hypothesis": "H1_real_directional",
                                "comparison_count": 2,
                                "comparisons": [{"passed": False}, {"passed": False}],
                                "outcome": "failed",
                                "passed": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (logs / "test_debug_20250101T000000Z.json").write_text(
                json.dumps(
                    {
                        "preset": "debug",
                        "timestamp_utc": "20250101T000000Z",
                        "configure_exit": 0,
                        "build_exit": 1,
                        "ctest_exit": 1,
                    }
                ),
                encoding="utf-8",
            )
            (logs / "test_debug_20260101T000000Z.json").write_text(
                json.dumps(
                    {
                        "preset": "debug",
                        "timestamp_utc": "20260101T000000Z",
                        "configure_exit": 0,
                        "build_exit": 0,
                        "ctest_exit": 0,
                    }
                ),
                encoding="utf-8",
            )
            dataset_catalog.write_text(
                "\n".join(
                    [
                        "schema: rch.real_dataset_catalog.v1",
                        "datasets:",
                        "  - id: stanford_bunny",
                        "    family: Stanford",
                        "    status: measured",
                        "    source_url: https://graphics.stanford.edu/data/3Dscanrep/",
                        "  - id: modelnet40",
                        "    family: ModelNet40",
                        "    status: protocol_only_not_run",
                        "    source_url: https://modelnet.cs.princeton.edu/",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = make_paper_artifacts(
                Namespace(
                    synthetic_results_dir=synthetic_primary,
                    synthetic_refinement_results_dir=synthetic,
                    real_results_dir=real_primary,
                    real_refinement_results_dir=real,
                    a7_results_dir=a7,
                    logs_dir=logs,
                    figures_dir=figures,
                    outputs_dir=outputs,
                    tables_dir=tables,
                    stats_dir=stats,
                    dataset_catalog=dataset_catalog,
                )
            )
            self.assertEqual(len(manifest["figures"]), 12)
            self.assertIn("fig_schema_method_pipeline.pdf", manifest["figures"])
            self.assertIn(
                "fig_schema_rch_implementation_flow.pdf", manifest["figures"]
            )
            self.assertEqual(len(manifest["tables"]), 6)
            self.assertEqual(manifest["inputs"]["a7_rows"], 2)
            self.assertEqual(manifest["inputs"]["dataset_catalog_rows"], 2)
            self.assertGreater(manifest["inputs"]["synthetic_refinement_rows"], 2)
            self.assertEqual(manifest["inputs"]["real_refinement_rows"], 2)
            self.assertEqual(
                manifest["stats"]["synthetic_refinement_effects.csv"]["row_count"],
                1,
            )
            self.assertEqual(
                manifest["stats"]["real_refinement_effects.csv"]["row_count"], 1
            )
            self.assertEqual(manifest["outputs"]["status"], "generated")
            self.assertEqual(manifest["outputs"]["file_count"], 7)
            self.assertFalse((outputs / "synthetic_refinement").exists())
            self.assertFalse((outputs / "real_refinement").exists())
            self.assertFalse((outputs / "synthetic_dataset" / "orders").exists())
            self.assertTrue(
                (
                    outputs
                    / "synthetic_dataset"
                    / "all"
                    / "table_3_locality.csv"
                ).exists()
            )
            self.assertFalse((outputs / "real_dataset" / "off" / "manifests").exists())
            self.assertFalse(
                (outputs / "real_dataset" / "off" / "refinement_note.json").exists()
            )
            self.assertTrue(
                (
                    outputs / "a7_cgal_appendix" / "a7_cgal_spatial_sort.csv"
                ).exists()
            )
            self.assertTrue((outputs / "output_snapshot_manifest.json").exists())
            synthetic_effects = stats / "synthetic_refinement_effects.csv"
            self.assertTrue(synthetic_effects.exists())
            self.assertIn(
                "miad_all_minus_off",
                synthetic_effects.read_text(encoding="utf-8"),
            )
            effects = stats / "real_refinement_effects.csv"
            self.assertTrue(effects.exists())
            self.assertIn(
                "miad_all_minus_off",
                effects.read_text(encoding="utf-8"),
            )
            for filename in manifest["figures"]:
                self.assertTrue((figures / filename).exists())
            self.assertEqual(
                manifest["figures"]["fig_synthetic_block_read_cache_miss.pdf"][
                    "status"
                ],
                "generated_from_synthetic_m8_cache_miss_rate",
            )
            self.assertEqual(
                manifest["figures"]["fig_mixed_recall_heatmap.pdf"]["status"],
                "generated_from_synthetic_real",
            )
            mixed_recall = manifest["figures"]["fig_mixed_recall_heatmap.pdf"]
            self.assertEqual(mixed_recall["real_metric_column"], "recall_8_64")
            self.assertEqual(mixed_recall["real_metric_cells"], 1)
            self.assertEqual(mixed_recall["real_metric_status_counts"], {"exact": 1})
            self.assertNotIn("real_sampled_cells", mixed_recall)
            self.assertEqual(
                manifest["figures"]["fig_mixed_ablation_a5_vs_a6_miad.pdf"]["status"],
                "generated_from_synthetic_real",
            )
            self.assertIn("fig_mixed_bit_allocation_by_rule.pdf", manifest["figures"])
            self.assertNotIn("fig_mixed_c2_bit_allocation.pdf", manifest["figures"])
            self.assertIn(
                "fig_synthetic_contamination_tau_by_bit_rule.pdf", manifest["figures"]
            )
            self.assertNotIn(
                "fig_synthetic_clean_recall_heatmap.pdf", manifest["figures"]
            )
            self.assertNotIn(
                "fig_synthetic_ablation_a5_vs_a6_miad.pdf", manifest["figures"]
            )
            self.assertNotIn("fig_meta_application_scope.pdf", manifest["figures"])
            self.assertTrue((tables / "table_meta_determinism_by_preset.tex").exists())
            self.assertNotIn(
                "FAIL",
                (tables / "table_meta_determinism_by_preset.tex").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertFalse((tables / "table_meta_application_scope.tex").exists())
            self.assertTrue((tables / "table_mixed_claim_status.tex").exists())
            self.assertTrue((tables / "table_mixed_claim_status.csv").exists())
            self.assertTrue((tables / "table_mixed_claim_status.json").exists())
            self.assertTrue((tables / "table_mixed_metric_leaders.tex").exists())
            self.assertTrue(
                (tables / "table_mixed_rch_quantization_summary.tex").exists()
            )
            self.assertTrue((tables / "table_cgal_a7_fixture.tex").exists())
            self.assertTrue((tables / "table_real_dataset_catalog.tex").exists())
            self.assertIn(
                "csv",
                manifest["tables"]["table_mixed_claim_status.tex"]["formats"],
            )
            self.assertIn(
                "H1 real-data direction & Failed",
                (tables / "table_mixed_claim_status.tex").read_text(encoding="utf-8"),
            )
            self.assertTrue((stats / "paper_artifacts_manifest.json").exists())


class PaperArtifactRepoCoverageTest(unittest.TestCase):
    """Repository artifact coverage gates for the current generated outputs."""

    def test_generated_manifest_preserves_measured_and_unmeasured_statuses(
        self,
    ) -> None:
        manifest_path = ROOT / "analysis/generated/stats/paper_artifacts_manifest.json"
        if not manifest_path.exists():
            self.skipTest("generated paper artifact manifest is not present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertGreater(manifest["inputs"]["synthetic_rows"], 0)
        self.assertGreater(manifest["inputs"]["real_rows"], 0)
        self.assertGreater(manifest["inputs"]["a7_rows"], 0)
        self.assertEqual(
            manifest["figures"]["fig_synthetic_block_read_cache_miss.pdf"]["status"],
            "generated_from_synthetic_m8_cache_miss_rate",
        )
        self.assertIn("fig_schema_method_pipeline.pdf", manifest["figures"])
        self.assertIn("fig_schema_rch_implementation_flow.pdf", manifest["figures"])
        self.assertIn("fig_mixed_recall_heatmap.pdf", manifest["figures"])
        self.assertIn("fig_mixed_bit_allocation_by_rule.pdf", manifest["figures"])
        self.assertNotIn("fig_mixed_c2_bit_allocation.pdf", manifest["figures"])
        self.assertIn("fig_mixed_ablation_a5_vs_a6_miad.pdf", manifest["figures"])
        self.assertIn(
            "fig_synthetic_contamination_tau_by_bit_rule.pdf", manifest["figures"]
        )
        self.assertNotIn("fig_synthetic_clean_recall_heatmap.pdf", manifest["figures"])
        self.assertNotIn(
            "fig_synthetic_ablation_a5_vs_a6_miad.pdf", manifest["figures"]
        )
        self.assertNotIn("fig_meta_application_scope.pdf", manifest["figures"])
        self.assertNotIn("table_meta_application_scope.tex", manifest["tables"])
        self.assertIn("table_mixed_metric_leaders.tex", manifest["tables"])
        self.assertIn("table_mixed_rch_quantization_summary.tex", manifest["tables"])
        if manifest["inputs"]["test_logs"] == 0:
            table = (
                ROOT / "analysis/generated/tables/table_meta_determinism_by_preset.tex"
            ).read_text(encoding="utf-8")
            self.assertIn("Not verified", table)

    def test_synthetic_real_csv_outputs_cover_declared_current_artifact_axes(
        self,
    ) -> None:
        synthetic_dir = ROOT / "experiments/outputs/synthetic_dataset/off"
        real_dir = ROOT / "experiments/outputs/real_dataset/off"
        import csv

        required_paths = (
            synthetic_dir / "table_3_locality.csv",
            synthetic_dir / "table_4_outlier.csv",
            synthetic_dir / "table_5_runtime.csv",
            real_dir / "table_2_dataset_summary.csv",
        )
        missing = [path for path in required_paths if not path.exists()]
        if missing:
            self.skipTest(
                "benchmark outputs are not present: "
                + ", ".join(str(path.relative_to(ROOT)) for path in missing)
            )

        with (synthetic_dir / "table_3_locality.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            locality = list(csv.DictReader(handle))
        with (synthetic_dir / "table_4_outlier.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            outlier = list(csv.DictReader(handle))
        with (synthetic_dir / "table_5_runtime.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            runtime = list(csv.DictReader(handle))
        with (real_dir / "table_2_dataset_summary.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            real = list(csv.DictReader(handle))

        locality_runlist = read_yaml(
            ROOT / "experiments/runlists/table_3_locality.yaml"
        )
        outlier_runlist = read_yaml(ROOT / "experiments/runlists/table_4_outlier.yaml")
        runtime_runlist = read_yaml(ROOT / "experiments/runlists/table_5_runtime.yaml")
        real_runlist = read_yaml(
            ROOT / "experiments/runlists/table_2_dataset_summary.yaml"
        )

        self.assertEqual(
            len(locality),
            algorithm_bit_rule_count(locality_runlist)
            * len(locality_runlist["contamination_ids"])
            * len(locality_runlist["geometry_ids"])
            * len(locality_runlist["point_counts"])
            * len(locality_runlist["seeds"]),
        )
        self.assertEqual(
            set(row["geometry_id"] for row in locality),
            set(locality_runlist["geometry_ids"]),
        )
        self.assertEqual(
            set(row["contamination_id"] for row in locality),
            set(locality_runlist["contamination_ids"]),
        )
        self.assertEqual(
            set(row["bit_rule"] for row in locality),
            declared_bit_rule_ids(locality_runlist),
        )
        self.assertTrue(all(row.get("m1_l1_locality", "") for row in locality))
        self.assertTrue(all(row.get("m1_l2_locality", "") for row in locality))
        self.assertEqual(
            len(outlier),
            algorithm_bit_rule_count(outlier_runlist)
            * len(outlier_runlist["contamination_ids"])
            * len(outlier_runlist["geometry_ids"])
            * len(outlier_runlist["point_counts"])
            * len(outlier_runlist["seeds"]),
        )
        self.assertEqual(
            set(row["contamination_id"] for row in outlier),
            set(outlier_runlist["contamination_ids"]),
        )
        self.assertEqual(
            set(row["bit_rule"] for row in outlier),
            declared_bit_rule_ids(outlier_runlist),
        )
        self.assertEqual(
            len(runtime),
            algorithm_bit_rule_count(runtime_runlist)
            * len(runtime_runlist["contamination_ids"])
            * len(runtime_runlist["geometry_ids"])
            * len(runtime_runlist["point_counts"])
            * len(runtime_runlist["seeds"]),
        )
        self.assertEqual(
            set(row["contamination_id"] for row in runtime),
            set(runtime_runlist["contamination_ids"]),
        )
        self.assertEqual(
            set(row["bit_rule"] for row in runtime),
            declared_bit_rule_ids(runtime_runlist),
        )
        self.assertTrue(
            all(
                row.get("peak_rss_kb", "")
                for row in runtime
                if row["algorithm_id"] != "A7_cgal_spatial_sort"
            )
        )
        self.assertTrue(all(row.get("block_read_p95", "") for row in runtime))
        self.assertTrue(all(row.get("cache_miss_rate", "") for row in runtime))
        self.assertTrue(all(row.get("perf_status", "") == "ok" for row in runtime))
        self.assertIn("A7_cgal_spatial_sort", {row["algorithm_id"] for row in runtime})
        self.assertEqual(
            set(row["dataset_id"] for row in real),
            {"stanford_bunny", "stanford_armadillo"},
        )
        self.assertEqual(
            set(row["bit_rule"] for row in real),
            {rule["id"] for rule in real_runlist["bit_rules"]},
        )
        self.assertEqual(
            set(row["contamination_id"] for row in real),
            set(real_runlist.get("contamination_ids", ["D0"])),
        )
        self.assertEqual(
            set(row["seed"] for row in real),
            {str(seed) for seed in real_runlist.get("seeds", [0])},
        )


if __name__ == "__main__":
    unittest.main()
