"""Unit tests for synthetic generators and analysis helpers"""

from __future__ import annotations

import hashlib
import json
import math
import tarfile
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from analysis.scripts.make_tables import (
    PRIMARY_BIT_RULES,
    block_signflip_test,
    bootstrap_median_ci,
    cliffs_delta,
    cliffs_delta_within,
    grouped_table,
    h3_frame_stability,
    holm_bonferroni,
    latex_escape,
    mean_ci,
    paired_metric,
    read_result_csvs,
    spearman_rank_consistency,
    stratified_hypotheses,
    wilcoxon_hypotheses,
    write_table_bundle,
)


def _stratification_fixture() -> list[dict[str, object]]:
    """Minimal runner rows covering every primary bit rule at the gate size.

    One row per (bit_rule, geometry, seed, algorithm) so the pooled sample is
    len(PRIMARY_BIT_RULES) x 2 geometries x 2 seeds pairs per hypothesis, and each
    stratum holds exactly 2 x 2 = 4 of them.
    """
    algorithms = (
        "A6_rch",
        "A3_isotropic_hilbert",
        "A2_morton",
        "A7_cgal_spatial_sort",
    )
    rows: list[dict[str, object]] = []
    for rule_index, bit_rule in enumerate(PRIMARY_BIT_RULES):
        for geometry in ("E1", "E2"):
            for seed in (0, 1):
                for algorithm_index, algorithm in enumerate(algorithms):
                    rows.append(
                        {
                            "runlist": "table_3_locality",
                            "algorithm_id": algorithm,
                            "bit_rule": bit_rule,
                            "contamination_id": "D0",
                            "geometry_id": geometry,
                            "point_count": 384.0,
                            "seed": seed,
                            # RCH strictly lowest so every pair favours it
                            "miad": 1.0 + algorithm_index + rule_index + seed,
                        }
                    )
    return rows


from data.synthetic.generators.common import (
    SplitMix64,
    finite_point,
    read_xyz_csv,
    write_xyz_csv,
)
from data.synthetic.generators.contamination import (
    bounds,
    contaminate,
    inject_clustered,
    inject_uniform_bbox,
    outlier_count,
)
from data.synthetic.generators.cylinder import (
    CYLINDER_DIMS,
    cylinder_points,
    cylinder_xyz,
)
from data.synthetic.generators.degeneracy_cases import (
    collinear_points,
    coplanar_points,
    make_case,
)
from data.synthetic.generators.gaussian_ellipsoid import (
    GEOMETRY_AXES,
    apply_rotation,
    ellipsoid_points,
    rotation_matrix,
)
from data.synthetic.generators.mixed_density import (
    MIXTURE_FAMILIES,
    mixture_points,
    select_component,
)
from data.synthetic.generators.quantization_stress import stress_points
from data.synthetic.generators.surface_patch import (
    QUADRIC_COEFFS,
    halton_pair,
    patch_points,
)
from data.synthetic.generators.torus import TORUS_RADII, torus_points, torus_xyz
from experiments.runners.run_matrix import (
    MatrixCase,
    PerfCounters,
    block_read_locality,
    case_stem,
    dist2,
    effective_refinement_for_method,
    expand_runlist,
    frame_angle_rad,
    inversion_count,
    is_permutation_of_size,
    kendall_tau_against_clean,
    l1_locality,
    l2_locality,
    load_algorithm_configs,
    load_refinement_modes as load_synthetic_refinement_modes,
    load_sweep_items,
    load_yaml,
    mean_inter_adjacent_distance,
    method_uses_frame,
    parse_perf_stat,
    parse_frame_axes,
    recall_at_k_window,
    run_cgal_ordering,
    run_ordering,
)
from experiments.runners.run_cgal_appendix import (
    A7_FIXTURE_PATH,
    load_fixture,
    run_cgal_appendix,
)


class SyntheticGeneratorsTest(unittest.TestCase):
    """Edge-case coverage for Synthetic generator scripts."""

    def test_gaussian_ellipsoid_is_deterministic_and_finite(self) -> None:
        """Same seed and axes produce identical finite point triples."""
        first = ellipsoid_points(8, (5.0, 1.0, 1.0), 42)
        second = ellipsoid_points(8, (5.0, 1.0, 1.0), 42)
        self.assertEqual(first, second)
        self.assertTrue(
            all(all(math.isfinite(value) for value in point) for point in first)
        )

    def test_gaussian_ellipsoid_rejects_invalid_axes(self) -> None:
        """Non-positive axes fail closed instead of producing invalid inputs."""
        with self.assertRaises(ValueError):
            ellipsoid_points(4, (1.0, 0.0, 1.0), 7)

    def test_contamination_edge_cases(self) -> None:
        """D0 preserves points; D1/D4 append deterministic outliers."""
        points = ellipsoid_points(10, (1.0, 1.0, 1.0), 1)
        self.assertEqual(outlier_count(10, 0.25), 2)
        self.assertEqual(contaminate(points, "clean", 0.25, 3), points)
        self.assertEqual(len(inject_uniform_bbox(points, 0.2, 3)), 12)
        self.assertEqual(len(inject_clustered(points, 0.2, 3)), 12)
        with self.assertRaises(ValueError):
            contaminate(points, "unknown", 0.1, 3)

    def test_degeneracy_cases_have_expected_rank_shape(self) -> None:
        """Coplanar has z=0 and collinear has y=z=0."""
        plane = coplanar_points(5, 2)
        line = collinear_points(5, 2)
        self.assertTrue(all(point[2] == 0.0 for point in plane))
        self.assertTrue(all(point[1] == 0.0 and point[2] == 0.0 for point in line))
        with self.assertRaises(ValueError):
            make_case("not_a_case", 5, 0)


class SyntheticRunnerMetricsTest(unittest.TestCase):
    """Unit coverage for runner expansion and metric edge cases."""

    def test_expand_runlist_cross_product(self) -> None:
        """A × C × D × E × N × seed expansion is explicit and countable."""
        runlist = {
            "algorithm_ids": ["A"],
            "bit_rules": [{"id": "C", "bit_allocator": "frame_core_occupancy"}],
            "contamination_ids": ["D0", "D1"],
            "geometry_ids": ["E0"],
            "point_counts": [4, 8],
            "seeds": [0, 1],
        }
        cases = expand_runlist(
            runlist,
            {"A": {"id": "A", "method": "input"}},
            {"D0": {"id": "D0"}, "D1": {"id": "D1"}},
            {"E0": {"id": "E0"}},
        )
        self.assertEqual(len(cases), 8)

    def test_metrics_handle_singletons_and_identity_order(self) -> None:
        """Metric helpers avoid division-by-zero on small point clouds."""
        one = [(0.0, 0.0, 0.0)]
        self.assertEqual(mean_inter_adjacent_distance(one, [0]), 0.0)
        self.assertEqual(l1_locality(one, [0]), 0.0)
        self.assertEqual(l2_locality(one, [0]), 0.0)
        self.assertEqual(recall_at_k_window(one, [0]), 1.0)
        self.assertEqual(block_read_locality(one, [0]), (0.0, 0.0))
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        self.assertEqual(kendall_tau_against_clean([0, 1, 2], [0, 1, 2], 3), 1.0)
        self.assertLess(kendall_tau_against_clean([0, 1, 2], [2, 1, 0], 3), 0.0)
        self.assertEqual(inversion_count([3, 1, 2, 0]), 5)
        self.assertGreater(mean_inter_adjacent_distance(points, [0, 2, 1]), 0.0)
        self.assertEqual(
            block_read_locality(points, [0, 1, 2], block_size=3), (2.0, 2.0)
        )

    def test_metric_helpers_fail_closed_on_malformed_orders(self) -> None:
        """Malformed permutations return neutral fail-closed metric values."""
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        bad_order = [0, 0, 2]
        self.assertFalse(is_permutation_of_size(bad_order, len(points)))
        self.assertEqual(mean_inter_adjacent_distance(points, bad_order), 0.0)
        self.assertEqual(l1_locality(points, bad_order), 0.0)
        self.assertEqual(l2_locality(points, bad_order), 0.0)
        self.assertEqual(recall_at_k_window(points, bad_order), 0.0)
        self.assertEqual(block_read_locality(points, bad_order), (0.0, 0.0))
        self.assertEqual(kendall_tau_against_clean([0, 1, 2], [0, 2], 3), 0.0)

    def test_perf_stat_parser_and_rate_are_fail_closed(self) -> None:
        """M8 parser accepts perf CSV output and rejects unparseable output."""
        parsed = parse_perf_stat(
            "100,,cache-references,1000000,100.00,,\n7,,cache-misses,1000000,100.00,,\n"
        )
        self.assertEqual(parsed.status, "ok")
        self.assertEqual(parsed.cache_references, 100)
        self.assertEqual(parsed.cache_misses, 7)
        self.assertAlmostEqual(parsed.miss_rate or 0.0, 0.07)
        prefixed = parse_perf_stat(
            "26094,,cpu_atom/cache-references/,419460,100.00,,\n"
            "<not counted>,,cpu_core/cache-references/,0,0.00,,\n"
            "14133,,cpu_atom/cache-misses/,419460,100.00,,\n"
        )
        self.assertEqual(prefixed.status, "ok")
        self.assertEqual(prefixed.cache_references, 26094)
        self.assertEqual(prefixed.cache_misses, 14133)
        self.assertEqual(
            parse_perf_stat("Error: permission denied\n").status, "unparsed"
        )
        self.assertIsNone(
            PerfCounters(status="x", cache_references=0, cache_misses=1).miss_rate
        )


class SyntheticAnalysisTest(unittest.TestCase):
    """Unit coverage for Synthetic statistical helper functions."""

    def test_holm_bonferroni_is_monotone(self) -> None:
        """Holm adjusted p-values preserve step-down monotonicity."""
        adjusted = holm_bonferroni([0.01, 0.04, 0.03])
        self.assertEqual(adjusted, [0.03, 0.06, 0.06])

    def test_cliffs_delta_sign(self) -> None:
        """Lower RCH-like samples produce negative Cliff's delta."""
        self.assertLess(cliffs_delta([1.0, 2.0], [3.0, 4.0]), 0.0)

    def test_read_result_csvs_rejects_non_finite_numeric_cells(self) -> None:
        """Synthetic analysis fails closed on present NaN/Inf metric cells."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "table_3_locality.csv").write_text(
                "runlist,point_count,seed,miad\n"
                "table_3_locality,384,0,nan\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-finite numeric field"):
                read_result_csvs(root)

    def test_tempdir_available_for_generated_outputs(self) -> None:
        """Smoke-check Python can create isolated Synthetic output directories."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Path(tmp).exists())


class SyntheticCommonHelpersTest(unittest.TestCase):
    """Edge-case coverage for common.py SplitMix64 + I/O helpers."""

    def test_splitmix64_same_seed_produces_identical_stream(self) -> None:
        """Same seed ⇒ bit-identical 64-bit stream across instances."""
        a = SplitMix64(0xF9_AA_00)
        b = SplitMix64(0xF9_AA_00)
        for _ in range(64):
            self.assertEqual(a.next_u64(), b.next_u64())

    def test_splitmix64_outputs_stay_in_unsigned_64_bit_range(self) -> None:
        """All `next_u64()` outputs are in [0, 2^64)."""
        rng = SplitMix64(1)
        for _ in range(2048):
            value = rng.next_u64()
            self.assertGreaterEqual(value, 0)
            self.assertLess(value, 1 << 64)

    def test_splitmix64_uniform01_is_in_closed_open_unit_interval(self) -> None:
        """uniform01() ∈ [0, 1); never returns 1.0 exactly."""
        rng = SplitMix64(0xDEADBEEF)
        for _ in range(4096):
            value = rng.uniform01()
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 1.0)

    def test_splitmix64_uniform_reversed_range_returns_lower_endpoint(self) -> None:
        """uniform(lo, hi) treats hi <= lo as an empty range."""
        rng = SplitMix64(4)
        self.assertEqual(rng.uniform(3.0, 3.0), 3.0)
        self.assertEqual(rng.uniform(3.0, 2.0), 3.0)

    def test_splitmix64_gaussian_pair_returns_finite_normals(self) -> None:
        """gaussian_pair never returns NaN / ±Inf even under adversarial draws."""
        rng = SplitMix64(0x12345678)
        for _ in range(2048):
            pair = rng.gaussian_pair()
            self.assertTrue(all(math.isfinite(value) for value in pair))

    def test_finite_point_rejects_nan_inf_and_wrong_arity(self) -> None:
        """finite_point returns False for non-3D or non-finite inputs."""
        self.assertFalse(finite_point((1.0, 2.0)))
        self.assertFalse(finite_point((1.0, 2.0, math.nan)))
        self.assertFalse(finite_point((1.0, 2.0, math.inf)))
        self.assertFalse(finite_point(("x", 2.0, 3.0)))  # type: ignore[arg-type]
        self.assertTrue(finite_point((1.0, 2.0, 3.0)))

    def test_xyz_csv_round_trip_preserves_finite_points(self) -> None:
        """write_xyz_csv ↔ read_xyz_csv round-trips finite triples bit-equal."""
        points = ellipsoid_points(8, (1.0, 2.0, 3.0), 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloud.csv"
            write_xyz_csv(path, points)
            self.assertEqual(read_xyz_csv(path), points)

    def test_write_xyz_csv_rejects_non_finite_points(self) -> None:
        """Writer fails closed before producing NaN/Inf fixture files."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            with self.assertRaises(ValueError):
                write_xyz_csv(path, [(1.0, 2.0, math.nan)])

    def test_read_xyz_csv_rejects_wrong_column_count_and_non_finite(self) -> None:
        """Reader fails closed on column-count and finiteness violations."""
        with tempfile.TemporaryDirectory() as tmp:
            bad_arity = Path(tmp) / "bad_arity.csv"
            bad_arity.write_text("1.0,2.0\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_xyz_csv(bad_arity)
            bad_inf = Path(tmp) / "bad_inf.csv"
            bad_inf.write_text("1.0,2.0,inf\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_xyz_csv(bad_inf)


class SyntheticGaussianEllipsoidTest(unittest.TestCase):
    """Edge-case coverage for gaussian_ellipsoid.py contracts."""

    def test_geometry_axes_table_matches_steps_md_5_1(self) -> None:
        self.assertEqual(GEOMETRY_AXES["sphere"], (1.0, 1.0, 1.0))
        self.assertEqual(GEOMETRY_AXES["plate_5to1"], (5.0, 1.0, 1.0))
        self.assertEqual(GEOMETRY_AXES["rod_10to1"], (10.0, 1.0, 1.0))

    def test_count_zero_returns_empty_list(self) -> None:
        """ellipsoid_points(0, …) ⇒ empty list (defensive)."""
        self.assertEqual(ellipsoid_points(0, (1.0, 1.0, 1.0), 5), [])

    def test_negative_count_raises(self) -> None:
        """Negative count is rejected fail-closed."""
        with self.assertRaises(ValueError):
            ellipsoid_points(-1, (1.0, 1.0, 1.0), 0)

    def test_non_finite_axes_raise(self) -> None:
        """NaN/Inf axes are rejected before Gaussian scaling."""
        for axes in ((math.nan, 1.0, 1.0), (1.0, math.inf, 1.0)):
            with self.subTest(axes=axes):
                with self.assertRaises(ValueError):
                    ellipsoid_points(1, axes, 0)

    def test_rotation_matrix_is_orthogonal(self) -> None:
        """R · Rᵀ ≈ I (bound 1e-12) for several seeds."""
        for seed in (0, 1, 42, 0x6A09E667):
            r = rotation_matrix(seed)
            for i in range(3):
                for j in range(3):
                    dot = sum(r[i][k] * r[j][k] for k in range(3))
                    expected = 1.0 if i == j else 0.0
                    self.assertAlmostEqual(dot, expected, delta=1e-12)

    def test_apply_rotation_preserves_norm(self) -> None:
        """Rotation preserves Euclidean norm to 1e-12."""
        r = rotation_matrix(13)
        original = (3.0, -1.0, 4.0)
        rotated = apply_rotation(original, r)
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in original)),
            math.sqrt(sum(value * value for value in rotated)),
            delta=1e-12,
        )


class SyntheticContaminationGeometryTest(unittest.TestCase):
    """Edge-case coverage for contamination.py geometry invariants."""

    def test_bounds_handles_empty_input(self) -> None:
        """bounds([]) returns origin tuples (defensive)."""
        lo, hi = bounds([])
        self.assertEqual(lo, (0.0, 0.0, 0.0))
        self.assertEqual(hi, (0.0, 0.0, 0.0))

    def test_outlier_count_rejects_negative_inputs(self) -> None:
        """Negative clean_count or fraction fails closed."""
        with self.assertRaises(ValueError):
            outlier_count(-1, 0.1)
        with self.assertRaises(ValueError):
            outlier_count(10, -0.1)

    def test_outlier_count_rejects_non_finite_fraction(self) -> None:
        """NaN/Inf contamination fractions fail closed."""
        for fraction in (math.nan, math.inf):
            with self.subTest(fraction=fraction):
                with self.assertRaises(ValueError):
                    outlier_count(10, fraction)

    def test_uniform_bbox_outliers_lie_outside_clean_bbox(self) -> None:
        """Each injected outlier lies beyond the original axis-aligned bbox."""
        clean = ellipsoid_points(20, (1.0, 1.0, 1.0), 7)
        contaminated = inject_uniform_bbox(clean, 0.5, 7)
        lo, hi = bounds(clean)
        for outlier in contaminated[len(clean) :]:
            outside = any(
                outlier[axis] < lo[axis] or outlier[axis] > hi[axis]
                for axis in range(3)
            )
            self.assertTrue(outside)

    def test_clustered_outliers_lie_near_remote_center(self) -> None:
        """Clustered outliers concentrate near (hi + 3·span) per axis."""
        clean = ellipsoid_points(20, (1.0, 1.0, 1.0), 5)
        contaminated = inject_clustered(clean, 0.3, 5)
        lo, hi = bounds(clean)
        for outlier in contaminated[len(clean) :]:
            for axis in range(3):
                span = max(hi[axis] - lo[axis], 1.0)
                expected = hi[axis] + 3.0 * span
                self.assertAlmostEqual(outlier[axis], expected, delta=0.5 * span)

    def test_clustered_and_uniform_streams_are_disjoint(self) -> None:
        """Substream isolation: clustered and uniform-bbox produce different points."""
        clean = ellipsoid_points(10, (1.0, 1.0, 1.0), 3)
        bbox = inject_uniform_bbox(clean, 0.5, 3)
        cluster = inject_clustered(clean, 0.5, 3)
        self.assertNotEqual(bbox[len(clean) :], cluster[len(clean) :])

    def test_contaminate_zero_fraction_returns_clone(self) -> None:
        """fraction=0 across modes leaves the cloud untouched."""
        clean = ellipsoid_points(8, (1.0, 1.0, 1.0), 9)
        for mode in ("clean", "uniform_bbox", "clustered"):
            self.assertEqual(contaminate(clean, mode, 0.0, 9), clean)


class SyntheticDegeneracyEdgeTest(unittest.TestCase):
    """Edge-case coverage for degeneracy_cases.py invariants."""

    def test_count_zero_returns_empty_for_both_cases(self) -> None:
        """coplanar/collinear with count=0 ⇒ empty list."""
        self.assertEqual(coplanar_points(0, 0), [])
        self.assertEqual(collinear_points(0, 0), [])

    def test_negative_count_raises_for_both_cases(self) -> None:
        """coplanar/collinear with count<0 raise ValueError."""
        with self.assertRaises(ValueError):
            coplanar_points(-1, 0)
        with self.assertRaises(ValueError):
            collinear_points(-1, 0)

    def test_make_case_dispatcher_matches_helpers(self) -> None:
        """make_case routes to the named helper with identical output."""
        self.assertEqual(make_case("coplanar", 4, 1), coplanar_points(4, 1))
        self.assertEqual(make_case("collinear", 4, 1), collinear_points(4, 1))


class SyntheticSurfaceFamilyTest(unittest.TestCase):
    """Edge-case coverage for cylinder, torus, and surface-patch generators."""

    def test_cylinder_points_stay_on_lateral_surface(self) -> None:
        """Generated points satisfy x² + y² = r² and z ∈ [-H/2,H/2]."""
        radius, height = CYLINDER_DIMS["standard"]
        self.assertEqual(cylinder_points(0, "standard", 0), [])
        for x, y, z in cylinder_points(16, "standard", 3):
            self.assertAlmostEqual((x * x) + (y * y), radius * radius, delta=1e-12)
            self.assertGreaterEqual(z, -0.5 * height)
            self.assertLess(z, 0.5 * height)
        self.assertEqual(cylinder_xyz(0.0, 2.0, radius), (radius, 0.0, 2.0))

    def test_cylinder_rejects_invalid_family_count_and_dims(self) -> None:
        """Cylinder family table entries must be finite positive dimensions."""
        with self.assertRaises(ValueError):
            cylinder_points(-1, "standard", 0)
        with self.assertRaises(ValueError):
            cylinder_points(1, "missing", 0)
        CYLINDER_DIMS["bad_nan"] = (math.nan, 1.0)
        try:
            with self.assertRaises(ValueError):
                cylinder_points(1, "bad_nan", 0)
        finally:
            del CYLINDER_DIMS["bad_nan"]

    def test_torus_points_stay_on_parametric_surface(self) -> None:
        """Generated points satisfy (sqrt(x²+y²)-R)² + z² = r²."""
        R, r = TORUS_RADII["standard"]
        self.assertEqual(torus_points(0, "standard", 0), [])
        for x, y, z in torus_points(16, "standard", 5):
            radial = math.sqrt((x * x) + (y * y))
            self.assertAlmostEqual(((radial - R) ** 2) + (z * z), r * r, delta=1e-12)
        self.assertEqual(torus_xyz(0.0, 0.0, R, r), (R + r, 0.0, 0.0))

    def test_torus_rejects_invalid_family_count_and_radii(self) -> None:
        """Torus radii must be finite and satisfy 0 < r < R."""
        with self.assertRaises(ValueError):
            torus_points(-1, "standard", 0)
        with self.assertRaises(ValueError):
            torus_points(1, "missing", 0)
        TORUS_RADII["bad_inf"] = (1.0, math.inf)
        try:
            with self.assertRaises(ValueError):
                torus_points(1, "bad_inf", 0)
        finally:
            del TORUS_RADII["bad_inf"]

    def test_surface_patch_halton_and_quadric_contract(self) -> None:
        """Patch coordinates use Halton bases 2/3 and finite quadric z values."""
        self.assertEqual(halton_pair(1), (0.5, 1.0 / 3.0))
        self.assertEqual(patch_points(0, "paraboloid_low", 0), [])
        for x, y, z in patch_points(16, "paraboloid_low", 7):
            self.assertGreaterEqual(x, -1.0)
            self.assertLess(x, 1.0)
            self.assertGreaterEqual(y, -1.0)
            self.assertLess(y, 1.0)
            self.assertTrue(math.isfinite(z))

    def test_surface_patch_rejects_invalid_family_count_and_coeffs(self) -> None:
        """Quadric coefficients must be finite and sigma_z non-negative."""
        with self.assertRaises(ValueError):
            patch_points(-1, "paraboloid_low", 0)
        with self.assertRaises(ValueError):
            patch_points(1, "missing", 0)
        QUADRIC_COEFFS["bad_sigma"] = (0.1, 0.2, math.nan)
        try:
            with self.assertRaises(ValueError):
                patch_points(1, "bad_sigma", 0)
        finally:
            del QUADRIC_COEFFS["bad_sigma"]


class SyntheticMixedDensityAndQuantizationTest(unittest.TestCase):
    """Edge-case coverage for mixed-density and quantization-stress generators."""

    def test_select_component_rejects_bad_weights(self) -> None:
        """Categorical CDF rejects negative, zero-sum, NaN, and Inf weights."""
        rng = SplitMix64(1)
        for weights in ((0.0, 0.0), (-1.0, 2.0), (math.nan, 1.0), (math.inf, 1.0)):
            with self.subTest(weights=weights):
                with self.assertRaises(ValueError):
                    select_component(rng, weights)

    def test_mixture_points_are_deterministic_and_finite(self) -> None:
        """Same seed/family yields identical finite Gaussian-mixture triples."""
        first = mixture_points(12, "three_blobs", 11)
        second = mixture_points(12, "three_blobs", 11)
        self.assertEqual(first, second)
        self.assertTrue(all(finite_point(point) for point in first))
        self.assertEqual(mixture_points(0, "three_blobs", 0), [])

    def test_mixture_rejects_invalid_family_count_and_components(self) -> None:
        """Mixture family specs require finite center, sigma > 0, and weight >= 0."""
        with self.assertRaises(ValueError):
            mixture_points(-1, "three_blobs", 0)
        with self.assertRaises(ValueError):
            mixture_points(1, "missing", 0)
        MIXTURE_FAMILIES["bad_sigma"] = (  # type: ignore[assignment]
            ((0.0, 0.0, 0.0), math.nan, 1.0),
        )
        try:
            with self.assertRaises(ValueError):
                mixture_points(1, "bad_sigma", 0)
        finally:
            del MIXTURE_FAMILIES["bad_sigma"]

    def test_quantization_stress_scenarios_are_finite_and_bounded(self) -> None:
        """Stress fixtures exercise aspect, boundary, and signed-zero cases."""
        self.assertEqual(stress_points(0, "extreme_aspect", 0), [])
        self.assertTrue(
            all(
                finite_point(point)
                for point in stress_points(32, "extreme_aspect", 2)
            )
        )
        near = stress_points(32, "near_integer_boundary", 2)
        self.assertTrue(
            all(abs(coord - round(coord)) < 1.0e-12 for point in near for coord in point)
        )
        signed = stress_points(64, "signed_zero_mix", 2)
        self.assertTrue(all(point[2] == 0.0 for point in signed))
        self.assertIn(-1.0, {math.copysign(1.0, point[2]) for point in signed})
        with self.assertRaises(ValueError):
            stress_points(-1, "extreme_aspect", 0)
        with self.assertRaises(ValueError):
            stress_points(1, "missing", 0)


class DataManifestIntegrityTest(unittest.TestCase):
    """Local integrity checks for data/ manifests and bundled demo archives."""

    def test_demo_manifest_sha256_matches_local_archives(self) -> None:
        """Pinned demo archives match SHA, inner path, and finite PLY vertex count."""
        repo = Path(__file__).resolve().parents[2]
        manifest = load_yaml(repo / "data/manifests/rch_demo.yml")
        for dataset in manifest["datasets"]:
            archive = repo / dataset["url"]
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(digest, dataset["sha256"])
            with tarfile.open(archive, "r:gz") as tar:
                self.assertIn(dataset["inner_path"], tar.getnames())
                payload = (
                    tar.extractfile(dataset["inner_path"])
                    .read()
                    .decode("ascii")
                    .splitlines()
                )
            self.assertEqual(payload[0], "ply")
            self.assertEqual(payload[1], "format ascii 1.0")
            declared_vertices = int(
                next(
                    line for line in payload if line.startswith("element vertex ")
                ).split()[2]
            )
            self.assertEqual(declared_vertices, dataset["expected_vertices"])
            end_header = payload.index("end_header")
            rows = payload[end_header + 1 : end_header + 1 + declared_vertices]
            self.assertEqual(len(rows), declared_vertices)
            for row in rows:
                values = [float(part) for part in row.split()]
                self.assertEqual(len(values), 3)
                self.assertTrue(all(math.isfinite(value) for value in values))

    def test_stanford_manifest_declares_expected_reference_counts(self) -> None:
        """Bunny/Armadillo entries keep the Stanford source counts pinned."""
        repo = Path(__file__).resolve().parents[2]
        manifest = load_yaml(repo / "data/manifests/stanford_3d_scanning.yml")
        datasets = {dataset["id"]: dataset for dataset in manifest["datasets"]}
        self.assertEqual(datasets["stanford_bunny"]["expected_vertices"], 35947)
        self.assertEqual(datasets["stanford_bunny"]["expected_faces"], 69451)
        self.assertEqual(datasets["stanford_armadillo"]["expected_vertices"], 172974)
        self.assertEqual(datasets["stanford_armadillo"]["expected_faces"], 345944)


class SyntheticMetricBoundaryTest(unittest.TestCase):
    """Edge-case coverage for run_matrix.py M1–M4 metric helpers."""

    def test_dist2_is_zero_for_identical_points(self) -> None:
        """dist2(p, p) == 0 for any finite p."""
        self.assertEqual(dist2((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)), 0.0)

    def test_miad_two_point_cloud_equals_segment_length(self) -> None:
        """MIAD on n=2 reduces to the single inter-adjacent distance."""
        points = [(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]
        self.assertAlmostEqual(mean_inter_adjacent_distance(points, [0, 1]), 5.0)

    def test_l1_locality_is_zero_when_points_coincide(self) -> None:
        """All-coincident points yield zero locality (degenerate baseline)."""
        coincident = [(0.0, 0.0, 0.0)] * 4
        self.assertEqual(l1_locality(coincident, [0, 1, 2, 3]), 0.0)
        self.assertEqual(l2_locality(coincident, [0, 1, 2, 3]), 0.0)

    def test_l1_is_max_and_l2_is_min_ratio(self) -> None:
        """L1 is the worst-case (max) and L2 the best-case (min) ratio."""
        # \(x=0,1,2,3\) in identity order: pair ratios \(d^3/gap\) are
        # \(\{1,4,9,1,4,1\}\); max = 9 (\(L_1\)), min = 1 (\(L_2\)).
        points = [(float(i), 0.0, 0.0) for i in range(4)]
        order = [0, 1, 2, 3]
        self.assertEqual(l1_locality(points, order), 9.0)
        self.assertEqual(l2_locality(points, order), 1.0)

    def test_accelerated_l1_l2_match_bruteforce_ratios(self) -> None:
        """Exact metric accelerators preserve the all-pairs M1 definitions."""
        points = [
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 3.0, 0.0),
            (0.0, 0.0, 4.0),
            (1.0, 1.0, 1.0),
        ]
        order = [4, 1, 3, 0, 2]
        rank = {raw: pos for pos, raw in enumerate(order)}
        values = []
        for left in range(len(points)):
            for right in range(left + 1, len(points)):
                gap = abs(rank[left] - rank[right])
                values.append((dist2(points[left], points[right]) ** 0.5) ** 3 / gap)

        self.assertAlmostEqual(l1_locality(points, order), max(values))
        self.assertAlmostEqual(l2_locality(points, order), min(values))

    def test_large_l2_accelerator_keeps_exact_line_case(self) -> None:
        """The kd-tree L2 path remains exact on a large monotone line cloud."""
        points = [(float(index), 0.0, 0.0) for index in range(2050)]
        order = list(range(len(points)))

        self.assertEqual(l2_locality(points, order), 1.0)

    def test_recall_at_k_window_clamps_to_unit_interval(self) -> None:
        """recall@k_w is bounded in [0, 1] across permutations."""
        points = [(float(i), 0.0, 0.0) for i in range(8)]
        identity = list(range(8))
        reverse = list(reversed(identity))
        self.assertGreaterEqual(recall_at_k_window(points, identity, 3, 4), 0.0)
        self.assertLessEqual(recall_at_k_window(points, identity, 3, 4), 1.0)
        self.assertGreaterEqual(recall_at_k_window(points, reverse, 3, 4), 0.0)
        self.assertLessEqual(recall_at_k_window(points, reverse, 3, 4), 1.0)

    def test_recall_at_k_window_clamps_k_to_n_minus_one(self) -> None:
        """k > n-1 is clamped silently; small clouds remain valid."""
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        self.assertGreaterEqual(recall_at_k_window(points, [0, 1, 2], 100, 4), 0.0)

    def test_recall_at_k_window_accepts_empty_knn_request(self) -> None:
        """k <= 0 is an empty-neighbour query and returns vacuous full recall."""
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        self.assertEqual(recall_at_k_window(points, [0, 1, 2], 0, 4), 1.0)

    def test_accelerated_recall_matches_tie_broken_bruteforce(self) -> None:
        """KD-tree recall keeps the old (distance, raw_index) tie contract."""
        points = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0),
        ]
        order = [0, 2, 4, 1, 3]
        k = 2
        window = 2
        rank = {raw: pos for pos, raw in enumerate(order)}
        half = max(1, window // 2)
        total = 0.0
        for raw in range(len(points)):
            exact = sorted(
                (dist2(points[raw], points[other]), other)
                for other in range(len(points))
                if other != raw
            )[:k]
            exact_set = {other for _, other in exact}
            left = max(0, rank[raw] - half)
            right = min(len(points), rank[raw] + half + 1)
            window_set = {order[pos] for pos in range(left, right) if order[pos] != raw}
            total += len(exact_set & window_set) / float(k)
        expected = total / float(len(points))

        self.assertEqual(recall_at_k_window(points, order, k, window), expected)

    def test_kendall_tau_filters_outlier_indices(self) -> None:
        """Indices >= clean_count are filtered before τ is computed."""
        clean_order = [0, 1, 2]
        contaminated_order = [0, 3, 1, 4, 2]
        self.assertAlmostEqual(
            kendall_tau_against_clean(clean_order, contaminated_order, 3),
            1.0,
        )

    def test_kendall_tau_returns_one_when_filtered_count_below_two(self) -> None:
        """Fewer than 2 retained originals ⇒ τ = 1.0 (vacuously concordant)."""
        self.assertEqual(kendall_tau_against_clean([0], [0, 5, 6], 1), 1.0)

    def test_frame_angle_rad_is_sign_invariant_and_bounded(self) -> None:
        """M5 uses acute corresponding-axis angles, so eigenvector sign flips are harmless."""
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        sign_flip = [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]
        quarter_turn = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]

        same = frame_angle_rad(identity, identity)
        flipped = frame_angle_rad(identity, sign_flip)
        rotated = frame_angle_rad(identity, quarter_turn)
        self.assertIsNotNone(same)
        self.assertIsNotNone(flipped)
        self.assertIsNotNone(rotated)
        self.assertAlmostEqual(same, 0.0)
        self.assertAlmostEqual(flipped, 0.0)
        self.assertAlmostEqual(rotated, math.pi / 2.0)
        self.assertIsNone(
            frame_angle_rad(
                identity, [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            )
        )

    def test_parse_frame_axes_rejects_malformed_manifest_values(self) -> None:
        """Manifest frame_axes must be a finite 3×3 numeric matrix."""
        good = {"frame_axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
        self.assertEqual(
            parse_frame_axes(good), [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        )
        self.assertIsNone(parse_frame_axes({}))
        self.assertIsNone(parse_frame_axes({"frame_axes": [[1.0, 0.0], [0.0, 1.0]]}))
        self.assertIsNone(
            parse_frame_axes(
                {"frame_axes": [[1.0, math.nan, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}
            )
        )

    def test_method_uses_frame_marks_m5_applicability(self) -> None:
        """M5 is applicable to frame-based methods, not AABB/no-frame baselines."""
        self.assertTrue(method_uses_frame("pca_compact_hilbert"))
        self.assertTrue(method_uses_frame("robust_frame_morton"))
        self.assertTrue(method_uses_frame("rch"))
        self.assertFalse(method_uses_frame("compact_hilbert_aabb"))
        self.assertFalse(method_uses_frame("morton"))


class SyntheticRunlistExpansionTest(unittest.TestCase):
    """Edge-case coverage for runlist expansion + filename derivation."""

    # C2_occupancy_floor10 was removed: its floor equals `equal_bits() = 10`, so it
    # emitted \(10/10/10\) and was byte-identical to C0_uniform.
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
    BIT_ALLOCATION_MODELS = [
        "fixed_equal_depth",
        "extent_ranked_monotone_half",
        "covering_occupancy_floor1",
        "robust_core_occupancy",
        "robust_core_delta_covering_occupancy",
    ]
    BIT_BUDGET_PROJECTIONS = [
        "equal_depth_axis_cap",
        "extent_ranked_half_budget",
        "minimax_worst_cell_edge",
        "minimax_worst_cell_edge",
        "minimax_worst_cell_edge",
    ]

    def test_canonical_synthetic_runlists_use_same_algorithm_axis(self) -> None:
        """Locality, outlier, and runtime matrices expose the same A-axis."""
        repo = Path(__file__).resolve().parents[2]
        for name in ("table_3_locality", "table_4_outlier", "table_5_runtime"):
            runlist = load_yaml(repo / "experiments/runlists" / f"{name}.yaml")
            self.assertEqual(runlist["algorithm_ids"], self.ALGORITHM_IDS)

    def test_config_loaders_reject_duplicate_ids(self) -> None:
        """Duplicate YAML ids fail closed instead of silently overwriting axes."""
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

            sweep = root / "sweep.yaml"
            sweep.write_text(
                "levels:\n"
                "  - id: D0\n"
                "    mode: clean\n"
                "  - id: D0\n"
                "    mode: clean\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate sweep item id"):
                load_sweep_items(sweep, "levels")

    def test_outlier_runlist_covers_all_synthetic_d_e_cells(self) -> None:
        """table_4_outlier covers the declared C axis where algorithms support C."""
        repo = Path(__file__).resolve().parents[2]
        expected_d = ["D0", "D1", "D2", "D3", "D4"]
        expected_e = ["E0", "E1", "E2", "E5", "E6", "E7", "E8"]
        runlist = load_yaml(repo / "experiments/runlists/table_4_outlier.yaml")
        self.assertEqual(runlist["contamination_ids"], expected_d)
        self.assertEqual(runlist["geometry_ids"], expected_e)
        self.assertEqual(
            [rule["id"] for rule in runlist["bit_rules"]],
            self.BIT_RULE_IDS,
        )
        self.assertIn("m1_l1_locality", runlist["metrics"])
        self.assertIn("m1_l2_locality", runlist["metrics"])
        self.assertIn("A6_rch_b2_mrcd", runlist["algorithm_ids"])
        self.assertIn("A6_rch_b3_ogk", runlist["algorithm_ids"])

        algorithms = load_algorithm_configs(repo / "experiments/configs/algorithms")
        self.assertEqual(algorithms["A6_rch"]["frame_estimator"], "det_mcd")
        self.assertEqual(algorithms["A6_rch_b2_mrcd"]["frame_estimator"], "mrcd")
        self.assertEqual(algorithms["A6_rch_b3_ogk"]["frame_estimator"], "ogk")
        contamination = load_sweep_items(
            repo / "experiments/configs/sweeps/contamination.yaml", "levels"
        )
        geometries = load_sweep_items(
            repo / "experiments/configs/sweeps/anisotropy.yaml", "geometries"
        )
        cases = expand_runlist(runlist, algorithms, contamination, geometries)
        supported_rule_count = 0
        for algorithm_id in runlist["algorithm_ids"]:
            supported = algorithms[algorithm_id].get("supported_bit_rules")
            if isinstance(supported, list):
                supported_rule_count += len(
                    {rule["id"] for rule in runlist["bit_rules"]}
                    & {str(item) for item in supported}
                )
            else:
                supported_rule_count += len(runlist["bit_rules"])
        expected_count = (
            supported_rule_count
            * len(expected_d)
            * len(expected_e)
            * len(runlist["point_counts"])
            * len(runlist["seeds"])
        )
        self.assertEqual(len(cases), expected_count)

        clean_seen: set[tuple[str, str, str, int, int]] = set()
        for case in cases:
            key = (
                str(case.algorithm["id"]),
                str(case.bit_rule["id"]),
                str(case.geometry["id"]),
                case.point_count,
                case.seed,
            )
            if case.contamination["id"] == "D0":
                clean_seen.add(key)
            else:
                self.assertIn(key, clean_seen)

    def test_locality_runlist_covers_declared_c_axis(self) -> None:
        """table_3_locality exposes all declared bit rules."""
        repo = Path(__file__).resolve().parents[2]
        runlist = load_yaml(repo / "experiments/runlists/table_3_locality.yaml")
        self.assertEqual(
            [rule["id"] for rule in runlist["bit_rules"]],
            self.BIT_RULE_IDS,
        )
        self.assertIn("m1_l1_locality", runlist["metrics"])
        self.assertIn("m1_l2_locality", runlist["metrics"])
        algorithms = load_algorithm_configs(repo / "experiments/configs/algorithms")
        contamination = load_sweep_items(
            repo / "experiments/configs/sweeps/contamination.yaml", "levels"
        )
        geometries = load_sweep_items(
            repo / "experiments/configs/sweeps/anisotropy.yaml", "geometries"
        )
        cases = expand_runlist(runlist, algorithms, contamination, geometries)
        self.assertEqual(
            {case.bit_rule["id"] for case in cases},
            set(self.BIT_RULE_IDS),
        )

    def test_runtime_runlist_covers_declared_c_axis(self) -> None:
        """table_5_runtime carries the declared C-axis artifact gate."""
        repo = Path(__file__).resolve().parents[2]
        runlist = load_yaml(repo / "experiments/runlists/table_5_runtime.yaml")
        self.assertEqual(
            [rule["id"] for rule in runlist["bit_rules"]],
            self.BIT_RULE_IDS,
        )
        self.assertEqual(
            [rule["bit_allocator"] for rule in runlist["bit_rules"]],
            self.BIT_ALLOCATORS,
        )
        self.assertIn("peak_rss_kb", runlist["metrics"])
        self.assertIn("cache_references", runlist["metrics"])
        self.assertIn("cache_misses", runlist["metrics"])
        self.assertIn("cache_miss_rate", runlist["metrics"])
        self.assertIn("perf_status", runlist["metrics"])
        self.assertIn("block_read_p95", runlist["metrics"])

        algorithms = load_algorithm_configs(repo / "experiments/configs/algorithms")
        contamination = load_sweep_items(
            repo / "experiments/configs/sweeps/contamination.yaml", "levels"
        )
        geometries = load_sweep_items(
            repo / "experiments/configs/sweeps/anisotropy.yaml", "geometries"
        )
        cases = expand_runlist(runlist, algorithms, contamination, geometries)
        bit_rules_by_algorithm = 0
        for algorithm_id in runlist["algorithm_ids"]:
            supported = algorithms[algorithm_id].get("supported_bit_rules")
            if isinstance(supported, list):
                bit_rules_by_algorithm += len(
                    {rule["id"] for rule in runlist["bit_rules"]}
                    & {str(item) for item in supported}
                )
            else:
                bit_rules_by_algorithm += len(runlist["bit_rules"])
        self.assertEqual(
            len(cases),
            bit_rules_by_algorithm
            * len(runlist["contamination_ids"])
            * len(runlist["geometry_ids"])
            * len(runlist["point_counts"])
            * len(runlist["seeds"]),
        )

    def test_canonical_runlists_record_bit_allocation_provenance(self) -> None:
        """Every canonical runlist carries explicit C-axis allocation provenance."""
        repo = Path(__file__).resolve().parents[2]
        for name in (
            "table_2_dataset_summary",
            "table_3_locality",
            "table_4_outlier",
            "table_5_runtime",
        ):
            runlist = load_yaml(repo / "experiments/runlists" / f"{name}.yaml")
            self.assertEqual(
                [rule["allocation_model"] for rule in runlist["bit_rules"]],
                self.BIT_ALLOCATION_MODELS,
                name,
            )
            self.assertEqual(
                [rule["budget_projection"] for rule in runlist["bit_rules"]],
                self.BIT_BUDGET_PROJECTIONS,
                name,
            )

    def test_expand_runlist_rejects_missing_bit_rules(self) -> None:
        """Empty / missing bit_rules fails closed."""
        with self.assertRaises(ValueError):
            expand_runlist(
                {
                    "algorithm_ids": ["A"],
                    "bit_rules": [],
                    "contamination_ids": ["D0"],
                    "geometry_ids": ["E0"],
                    "point_counts": [4],
                    "seeds": [0],
                },
                {"A": {"id": "A", "method": "input"}},
                {"D0": {"id": "D0"}},
                {"E0": {"id": "E0"}},
            )

    def test_case_stem_is_filesystem_safe_and_deterministic(self) -> None:
        """case_stem assembles a filesystem-safe identifier from all axes."""
        case = MatrixCase(
            algorithm={"id": "A6_rch", "method": "rch"},
            bit_rule={
                "id": "C3_frame_core_occupancy",
                "bit_allocator": "frame_core_occupancy",
            },
            contamination={"id": "D1", "mode": "uniform_bbox"},
            geometry={"id": "E1", "generator": "gaussian_ellipsoid"},
            point_count=128,
            seed=3,
        )
        stem = case_stem(case)
        self.assertEqual(stem, "A6_rch__C3_frame_core_occupancy__D1__E1__n128__s3")
        self.assertNotIn("/", stem)
        self.assertNotIn(" ", stem)

    def test_run_ordering_passes_timing_repeats_and_reads_manifest_seconds(
        self,
    ) -> None:
        """M6 timing repeats are measured inside rch_order and surfaced through manifest."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_rch_order.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "manifest = pathlib.Path(args['--manifest'])",
                        "counter = manifest.with_suffix(manifest.suffix + '.count')",
                        "seen = int(counter.read_text() or '0') if counter.exists() else 0",
                        "counter.write_text(str(seen + 1))",
                        "manifest.with_suffix("
                        "manifest.suffix + '.timing'"
                        ").write_text(args['--timing-repeats'])",
                        "manifest.with_suffix("
                        "manifest.suffix + '.refinement'"
                        ").write_text(args['--refinement'])",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n')",
                        "manifest.write_text(json.dumps({",
                        "    'hash': 'h',",
                        "    'bits_axis': [1, 1, 1],",
                        "    'robust_fallback_used': False,",
                        "    'frame_axes': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],",
                        "    'sort_seconds': 0.125,",
                        "    'peak_rss_kb': 1234,",
                        "}) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            case = MatrixCase(
                algorithm={"id": "A", "method": "rch"},
                bit_rule={"id": "C", "bit_allocator": "frame_core_occupancy"},
                contamination={"id": "D0", "mode": "clean"},
                geometry={"id": "E0", "generator": "gaussian_ellipsoid"},
                point_count=1,
                seed=0,
            )
            points = root / "points.csv"
            order = root / "order.csv"
            manifest = root / "manifest.json"
            points.write_text("0,0,0\n", encoding="utf-8")

            elapsed = run_ordering(
                fake,
                case,
                points,
                order,
                manifest,
                timing_repeats=3,
                refinement="all",
            )

            self.assertEqual(elapsed, 0.125)
            self.assertEqual((root / "manifest.json.count").read_text(), "1")
            self.assertEqual((root / "manifest.json.timing").read_text(), "3")
            self.assertEqual((root / "manifest.json.refinement").read_text(), "all")
            self.assertTrue(order.exists())
            self.assertTrue(manifest.exists())

    def test_input_ordering_forces_refinement_off_for_ablation_baseline(self) -> None:
        """The input baseline is recorded/executed as unrefined under all arms."""
        self.assertEqual(effective_refinement_for_method("input", "all"), "off")
        self.assertEqual(effective_refinement_for_method("rch", "all"), "all")
        modes, default = load_synthetic_refinement_modes()
        self.assertEqual(modes, ["off", "all"])
        self.assertEqual(default, "off")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_rch_order.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "manifest = pathlib.Path(args['--manifest'])",
                        "manifest.with_suffix("
                        "manifest.suffix + '.refinement'"
                        ").write_text(args['--refinement'])",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n')",
                        "manifest.write_text(json.dumps({'sort_seconds': 0.01}) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            case = MatrixCase(
                algorithm={"id": "A0_input", "method": "input"},
                bit_rule={"id": "C", "bit_allocator": "frame_core_occupancy"},
                contamination={"id": "D0", "mode": "clean"},
                geometry={"id": "E0", "generator": "gaussian_ellipsoid"},
                point_count=1,
                seed=0,
            )
            points = root / "points.csv"
            order = root / "order.csv"
            manifest = root / "manifest.json"
            points.write_text("0,0,0\n", encoding="utf-8")

            elapsed = run_ordering(fake, case, points, order, manifest, refinement="all")

            self.assertEqual(elapsed, 0.01)
            self.assertEqual((root / "manifest.json.refinement").read_text(), "off")

    def test_external_cgal_manifest_records_peak_rss_when_available(self) -> None:
        """A7 external adapter rows expose M7 instead of blanking peak_rss_kb."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_cgal.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n1,1,1\\n')",
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
            fake.chmod(0o755)
            case = MatrixCase(
                algorithm={
                    "id": "A7_cgal_spatial_sort",
                    "method": "external_cgal_spatial_sort",
                },
                bit_rule={
                    "id": "C3_frame_core_occupancy",
                    "bit_allocator": "frame_core_occupancy",
                },
                contamination={"id": "D0", "mode": "clean"},
                geometry={"id": "E0", "generator": "gaussian_ellipsoid"},
                point_count=2,
                seed=0,
            )
            points = root / "points.csv"
            points.write_text("0,0,0\n1,0,0\n", encoding="utf-8")
            manifest_path = root / "manifest.json"
            run_cgal_ordering(
                fake, case, points, root / "order.csv", manifest_path, timing_repeats=2
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["peak_rss_kb"] is not None:
                self.assertGreater(manifest["peak_rss_kb"], 0)

    def test_external_cgal_manifest_records_adapter_metadata(self) -> None:
        """A7 manifests carry CGAL version and spatial-sort parameter provenance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_cgal.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n1,1,1\\n')",
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
                        "if '--metadata-output' in args:",
                        "    pathlib.Path(args['--metadata-output']).write_text(json.dumps(metadata) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            case = MatrixCase(
                algorithm={
                    "id": "A7_cgal_spatial_sort",
                    "method": "external_cgal_spatial_sort",
                    "cgal_policy": "median",
                },
                bit_rule={
                    "id": "C3_frame_core_occupancy",
                    "bit_allocator": "frame_core_occupancy",
                },
                contamination={"id": "D0", "mode": "clean"},
                geometry={"id": "E0", "generator": "gaussian_ellipsoid"},
                point_count=2,
                seed=0,
            )
            points = root / "points.csv"
            points.write_text("0,0,0\n1,0,0\n", encoding="utf-8")
            manifest_path = root / "manifest.json"

            run_cgal_ordering(
                fake, case, points, root / "order.csv", manifest_path, timing_repeats=1
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["cgal"]["version"], "test-cgal")
            self.assertEqual(manifest["cgal"]["version_nr"], 123)
            self.assertEqual(manifest["cgal"]["git_hash"], "test-hash")
            self.assertEqual(manifest["cgal"]["spatial_sort_dimension"], 3)
            self.assertEqual(manifest["cgal"]["policy"], "median")
            self.assertEqual(manifest["cgal"]["threshold_hilbert"], 8)
            self.assertEqual(manifest["cgal"]["threshold_multiscale"], 64)
            self.assertEqual(manifest["cgal"]["ratio"], 0.125)

    def test_external_cgal_output_must_be_a_complete_permutation(self) -> None:
        """A7 fake adapters cannot feed duplicate or missing raw indices to metrics."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_cgal.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n0,0,0\\n1,0,1\\n')",
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
                        "if '--metadata-output' in args:",
                        "    pathlib.Path(args['--metadata-output']).write_text(json.dumps(metadata) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            case = MatrixCase(
                algorithm={
                    "id": "A7_cgal_spatial_sort",
                    "method": "external_cgal_spatial_sort",
                },
                bit_rule={
                    "id": "C3_frame_core_occupancy",
                    "bit_allocator": "frame_core_occupancy",
                },
                contamination={"id": "D0", "mode": "clean"},
                geometry={"id": "E0", "generator": "gaussian_ellipsoid"},
                point_count=2,
                seed=0,
            )
            points = root / "points.csv"
            points.write_text("0,0,0\n1,0,0\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                run_cgal_ordering(
                    fake,
                    case,
                    points,
                    root / "order.csv",
                    root / "manifest.json",
                    timing_repeats=1,
                )

    def test_cgal_appendix_manifest_records_adapter_metadata(self) -> None:
        """A7 appendix manifest records the adapter metadata for both policies."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_cgal.py"
            fake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))",
                        "pathlib.Path(args['--output']).write_text('rank,raw_index,key\\n' + '\\n'.join(f'{i},{i},0' for i in range(8)) + '\\n')",
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
                        "if '--metadata-output' in args:",
                        "    pathlib.Path(args['--metadata-output']).write_text(json.dumps(metadata) + '\\n')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            output_dir = root / "a7"

            run_cgal_appendix(Namespace(adapter_bin=fake, output_dir=output_dir))

            manifest = json.loads(
                (output_dir / "a7_cgal_spatial_sort.manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                set(manifest["cgal_metadata_by_policy"]), {"median", "middle"}
            )
            self.assertEqual(
                manifest["cgal_metadata_by_policy"]["median"]["cgal_version"],
                "test-cgal",
            )
            self.assertEqual(
                manifest["cgal_metadata_by_policy"]["middle"]["spatial_sort_policy"],
                "middle",
            )

    def test_a7_fixture_config_pins_recorded_points_and_policies(self) -> None:
        """The fixture YAML matches the recorded appendix permutation inputs."""
        points, policies = load_fixture(A7_FIXTURE_PATH)
        self.assertEqual(policies, ["median", "middle"])
        self.assertEqual(
            points,
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                (1.0, 1.0, 1.0),
                (0.25, 0.5, 0.75),
                (2.0, -1.0, 0.5),
                (-1.0, 2.0, 0.25),
            ],
        )

    def test_load_fixture_rejects_malformed_point_row(self) -> None:
        """A point row without exactly three coordinates fails closed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.yaml"
            path.write_text(
                "schema: rch.fixture.a7_cgal_appendix.v1\n"
                "policies: [median]\n"
                "points:\n"
                "  - [0.0, 1.0]\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_fixture(path)

    def test_load_fixture_rejects_duplicate_policies(self) -> None:
        """Duplicate policies would silently overwrite manifest entries."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.yaml"
            path.write_text(
                "schema: rch.fixture.a7_cgal_appendix.v1\n"
                "policies: [median, median]\n"
                "points:\n"
                "  - [0.0, 0.0, 0.0]\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_fixture(path)


class SyntheticAnalysisHelpersTest(unittest.TestCase):
    """Edge-case coverage for make_tables.py helpers."""

    def test_write_table_bundle_emits_tex_csv_and_json(self) -> None:
        """Generated tables have manuscript and machine-readable forms."""
        with tempfile.TemporaryDirectory() as tmp:
            tables = Path(tmp)
            outputs = write_table_bundle(
                tables,
                "table_fixture.tex",
                [{"algorithm_id": "A6_rch", "miad": "1.0"}],
                ["algorithm_id", "miad"],
                "Fixture table",
                "tab:fixture",
                "latex-body",
            )
            self.assertEqual(set(outputs), {"tex", "csv", "json"})
            self.assertEqual((tables / "table_fixture.tex").read_text(), "latex-body")
            self.assertIn("algorithm_id,miad", (tables / "table_fixture.csv").read_text())
            metadata = json.loads((tables / "table_fixture.json").read_text())
            self.assertEqual(metadata["schema"], "rch.generated_table.v1")
            self.assertEqual(metadata["rows"][0]["algorithm_id"], "A6_rch")

    def test_holm_bonferroni_handles_empty_and_singleton(self) -> None:
        """Empty / single-element inputs are pass-through."""
        self.assertEqual(holm_bonferroni([]), [])
        self.assertEqual(holm_bonferroni([0.04]), [0.04])

    def test_holm_bonferroni_clamps_to_unit_interval(self) -> None:
        """Adjusted p-values never exceed 1.0."""
        for value in holm_bonferroni([0.9, 0.95, 0.99]):
            self.assertLessEqual(value, 1.0)

    def test_cliffs_delta_at_boundaries(self) -> None:
        """δ ∈ [-1, 1]; identical samples yield 0; strict separation yields ±1."""
        self.assertEqual(cliffs_delta([], [1.0]), 0.0)
        self.assertEqual(cliffs_delta([1.0], []), 0.0)
        self.assertEqual(cliffs_delta([1.0, 2.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cliffs_delta([3.0, 4.0], [1.0, 2.0]), 1.0)
        self.assertEqual(cliffs_delta([1.0, 2.0], [3.0, 4.0]), -1.0)

    def test_cliffs_delta_within_at_boundaries(self) -> None:
        """d_w ∈ [-1, 1]; ties count in n but not in the numerator (Cliff 1993)."""
        self.assertEqual(cliffs_delta_within([], [1.0]), 0.0)
        self.assertEqual(cliffs_delta_within([1.0], []), 0.0)
        self.assertEqual(cliffs_delta_within([1.0, 2.0], [1.0]), 0.0)  # length mismatch
        self.assertEqual(cliffs_delta_within([1.0, 2.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cliffs_delta_within([3.0, 4.0], [1.0, 2.0]), 1.0)
        self.assertEqual(cliffs_delta_within([1.0, 2.0], [3.0, 4.0]), -1.0)
        # Three pairs: one up, one down, one tie, so \((1-1)/3=0\).
        self.assertEqual(cliffs_delta_within([2.0, 0.0, 5.0], [1.0, 1.0, 5.0]), 0.0)
        # Four pairs: three up, one down, so \((3-1)/4\).
        self.assertAlmostEqual(
            cliffs_delta_within([2.0, 2.0, 2.0, 0.0], [1.0, 1.0, 1.0, 1.0]), 0.5
        )

    def test_cliffs_delta_within_isolates_the_within_pair_effect(self) -> None:
        """The property that makes d_w the matched effect size for a paired test.

        Ten pairs, base values one unit apart, RCH better by the same fixed amount
        in EVERY pair. The paired evidence is identical in all three cases — every
        pair improves — so the paired effect size must be identical. Cliff's
        all-pairs δ is not: it scales with the shift relative to the between-pair
        spacing, because it mixes the within-pair change with the between-pair
        dominance (Cliff 1993, "Variance of d in the Paired Case": the all-pairs
        estimate "has expectation [d_W + (n - 1)*d]/n").
        """
        base = [float(index) for index in range(10)]
        deltas = []
        for shift in (0.5, 2.5, 5.5):
            rch = [value - shift for value in base]
            self.assertEqual(cliffs_delta_within(rch, base), -1.0)
            deltas.append(cliffs_delta(rch, base))
        self.assertAlmostEqual(deltas[0], -0.10)
        self.assertAlmostEqual(deltas[1], -0.44)
        self.assertAlmostEqual(deltas[2], -0.80)
        # \(d_w\) stays \(-1.0\) while \(|\delta_{\mathrm{Cliff}}|\) moves \(0.10\to0.80\).
        self.assertLess(deltas[2], deltas[1])
        self.assertLess(deltas[1], deltas[0])

    def test_block_signflip_reduces_to_exact_wilcoxon_with_one_stratum(self) -> None:
        """With a single stratum the block test IS the exact signed-rank test.

        This is the correctness anchor: whole-block sign flipping over n blocks of
        one observation each enumerates exactly the 2**n sign assignments that
        define the exact Wilcoxon signed-rank null, so the p-values must agree to
        the last digit.
        """
        from scipy.stats import wilcoxon as _wilcoxon

        cases = [
            [-1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -0.5, -7.0, -8.0, -9.0],
            [-1.0, 2.0, -3.0, 4.0, -5.0, -6.0, 0.5, -7.0, 8.0, -9.0],
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.5, 7.0, 8.0, 9.0],
        ]
        for differences in cases:
            blocks = [{"only": value} for value in differences]
            result = block_signflip_test(blocks, alternative="less")
            expected = _wilcoxon(differences, alternative="less", method="exact")
            self.assertAlmostEqual(result["p"], float(expected.pvalue), places=12)
            self.assertEqual(result["n_blocks"], len(differences))
            self.assertEqual(result["n_strata"], 1)
            self.assertIn("exact", result["method"])

    def test_block_signflip_matches_wilcoxon_when_zero_differences_exist(self) -> None:
        """Zero differences are dropped from ranks, matching Wilcoxon's rule."""
        from scipy.stats import wilcoxon as _wilcoxon

        differences = [0.0, -1.0, -2.0, 0.0, 3.0, -4.0, 0.0, -5.0]
        blocks = [{"only": value} for value in differences]

        result = block_signflip_test(blocks, alternative="less")
        nonzero = [value for value in differences if value != 0.0]
        expected = _wilcoxon(
            nonzero,
            alternative="less",
            method="exact",
        )

        self.assertAlmostEqual(result["p"], float(expected.pvalue), places=12)
        self.assertEqual(result["n_blocks"], 5)
        self.assertEqual(result["n_strata"], 1)

    def test_block_signflip_handles_all_zero_and_invalid_alternative(self) -> None:
        """All ties are neutral; unsupported alternatives fail closed."""
        result = block_signflip_test(
            [{"only": 0.0}, {"only": 0.0}], alternative="less"
        )
        self.assertEqual(result["p"], 1.0)
        self.assertEqual(result["statistic"], 0.0)
        self.assertEqual(result["n_blocks"], 0)
        self.assertEqual(result["n_strata"], 0)
        self.assertEqual(result["method"], "no_nonzero_differences")
        with self.assertRaises(ValueError):
            block_signflip_test([{"only": -1.0}], alternative="two-sided")

    def test_block_signflip_is_invariant_to_stratum_scale(self) -> None:
        """Within-stratum ranking keeps a large-scale stratum from dominating.

        Two strata, identical sign patterns, but one stratum's magnitudes are
        1000x the other's. Ranks are formed within stratum, so the result must not
        depend on that scale factor.
        """
        signs = [-1.0, -1.0, -1.0, 1.0, -1.0, -1.0, 1.0, -1.0, -1.0, -1.0]
        small = [
            {"a": sign * (index + 1), "b": sign * (index + 1)}
            for index, sign in enumerate(signs)
        ]
        blown_up = [
            {"a": sign * (index + 1), "b": sign * (index + 1) * 1000.0}
            for index, sign in enumerate(signs)
        ]
        self.assertAlmostEqual(
            block_signflip_test(small, alternative="less")["p"],
            block_signflip_test(blown_up, alternative="less")["p"],
            places=12,
        )

    def test_block_signflip_p_is_never_zero(self) -> None:
        """The observed arrangement is part of the enumerated null (Phipson & Smyth)."""
        blocks = [{"only": -float(index + 1)} for index in range(10)]
        result = block_signflip_test(blocks, alternative="less")
        self.assertGreaterEqual(result["p"], 1.0 / 1024.0)
        self.assertAlmostEqual(result["p"], 1.0 / 1024.0, places=12)

    def test_stratified_hypotheses_partitions_the_pooled_pairs(self) -> None:
        """Each stratum is one bit rule; together they partition the pooled sample.

        The pooled gate draws its pairs from all of PRIMARY_BIT_RULES, so the
        stratified per-rule pair counts must sum to the pooled count. That is the
        invariant which makes the stratification a re-partition of the same data
        rather than a different sample.
        """
        rows = _stratification_fixture()
        pooled = wilcoxon_hypotheses(rows)
        stratified = stratified_hypotheses(rows)
        # Each rule contributes the H1/H2/H7_A7 family plus the H3 diagnostic.
        self.assertEqual(len(stratified), 4 * len(PRIMARY_BIT_RULES))
        for item in pooled:
            per_rule = [
                entry for entry in stratified if entry["hypothesis"] == item["hypothesis"]
            ]
            self.assertEqual(len(per_rule), len(PRIMARY_BIT_RULES))
            self.assertEqual(sum(entry["n_pairs"] for entry in per_rule), item["n_pairs"])
        self.assertEqual({entry["bit_rule"] for entry in stratified}, set(PRIMARY_BIT_RULES))
        self.assertEqual({entry["bit_rule"] for entry in pooled}, {"pooled"})
        self.assertEqual(
            {entry["hypothesis"] for entry in stratified},
            {"H1", "H2", "H7_A7", "H3"},
        )

    def test_paired_metric_filters_runlist_and_contamination(self) -> None:
        """paired_metric drops rows outside table_3_locality / D0 / C2 / E1-E2 / N=384."""
        rows = [
            {
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E1",
                "point_count": 384.0,
                "seed": 0.0,
                "miad": 1.0,
            },
            {
                "runlist": "table_3_locality",
                "algorithm_id": "A2_morton",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E1",
                "point_count": 384.0,
                "seed": 0.0,
                "miad": 2.0,
            },
            {  # filtered: wrong runlist
                "runlist": "table_5_runtime",
                "algorithm_id": "A6_rch",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E1",
                "point_count": 384.0,
                "seed": 0.0,
                "miad": 0.0,
            },
            {  # filtered: wrong geometry
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E0",
                "point_count": 384.0,
                "seed": 0.0,
                "miad": 0.0,
            },
            {  # filtered: non-gate size (N=256 enriches the figure, not the gate)
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E1",
                "point_count": 256.0,
                "seed": 0.0,
                "miad": 9.0,
            },
            {  # filtered: non-gate size pair partner
                "runlist": "table_3_locality",
                "algorithm_id": "A2_morton",
                "contamination_id": "D0",
                "bit_rule": "C3_frame_core_occupancy",
                "geometry_id": "E1",
                "point_count": 256.0,
                "seed": 0.0,
                "miad": 9.0,
            },
        ]
        rch, base = paired_metric(rows, "A2_morton", "miad")
        self.assertEqual(rch, [1.0])
        self.assertEqual(base, [2.0])

    def test_bootstrap_median_ci_handles_empty_singleton_and_sample(self) -> None:
        """Bootstrap CI helper is deterministic and explicit on edge cases."""
        self.assertEqual(bootstrap_median_ci([])["method"], "not_available")
        singleton = bootstrap_median_ci([2.0])
        self.assertEqual(singleton["ci_low"], 2.0)
        sample = bootstrap_median_ci([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(sample["method"], "scipy.stats.bootstrap percentile")
        self.assertLessEqual(sample["ci_low"], sample["median"])
        self.assertGreaterEqual(sample["ci_high"], sample["median"])

    def test_spearman_rank_consistency_reports_each_bit_rule(self) -> None:
        """Spearman rho is computed per C-axis bit rule, not after pooling C0/C1/C2."""
        rows: list[dict[str, object]] = []
        for bit_rule in ("C0_uniform", "C1_monotone_half"):
            for geometry in ("E1", "E2"):
                for algorithm, value in (
                    ("A2_morton", 2.0),
                    ("A3_isotropic_hilbert", 1.0),
                    ("A6_rch", 0.5),
                ):
                    rows.append(
                        {
                            "runlist": "table_3_locality",
                            "algorithm_id": algorithm,
                            "bit_rule": bit_rule,
                            "contamination_id": "D0",
                            "geometry_id": geometry,
                            "point_count": 384.0,
                            "miad": value,
                        }
                    )
        # These rows must be excluded from the inferential Spearman summary;
        # if they were included their E1/E2 rank disagreement would drop \(\rho<1\).
        for geometry, value in (("E1", 0.01), ("E2", 9.0)):
            rows.append(  # non-gate size (N=256)
                {
                    "runlist": "table_3_locality",
                    "algorithm_id": "A2_morton",
                    "bit_rule": "C0_uniform",
                    "contamination_id": "D0",
                    "geometry_id": geometry,
                    "point_count": 256.0,
                    "miad": value,
                }
            )
            rows.append(  # excluded robust-frame variant (MRCD)
                {
                    "runlist": "table_3_locality",
                    "algorithm_id": "A6_rch_b2_mrcd",
                    "bit_rule": "C0_uniform",
                    "contamination_id": "D0",
                    "geometry_id": geometry,
                    "point_count": 384.0,
                    "miad": value,
                }
            )
        result = spearman_rank_consistency(rows, "miad")
        self.assertEqual(
            {item["scope"] for item in result},
            {"C0_uniform:E1_vs_E2", "C1_monotone_half:E1_vs_E2"},
        )
        self.assertTrue(all(item["rho"] == 1.0 for item in result))
        self.assertTrue(all(item["n_methods"] == 3 for item in result))

    def test_grouped_table_produces_one_row_per_unique_key(self) -> None:
        """grouped_table aggregates rows that share group_keys into one cell."""
        rows = [
            {
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "geometry_id": "E1",
                "point_count": 128.0,
                "miad": 1.0,
            },
            {
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "geometry_id": "E1",
                "point_count": 128.0,
                "miad": 2.0,
            },
            {  # different geometry → distinct row
                "runlist": "table_3_locality",
                "algorithm_id": "A6_rch",
                "geometry_id": "E2",
                "point_count": 128.0,
                "miad": 3.0,
            },
        ]
        table = grouped_table(
            rows, "table_3_locality", ["algorithm_id", "geometry_id"], ["miad"]
        )
        self.assertEqual(len(table), 2)

    def test_h3_frame_stability_reports_failed_direction_without_hiding_it(
        self,
    ) -> None:
        """H3 returns a diagnostic result instead of being omitted."""
        rows = [
            {
                "runlist": "table_4_outlier",
                "algorithm_id": "A6_rch",
                "bit_rule": "C3_frame_core_occupancy",
                "contamination_id": "D1",
                "geometry_id": "E1",
                "point_count": 128.0,
                "seed": 0.0,
                "kendall_tau_clean": 0.4,
            },
            {
                "runlist": "table_4_outlier",
                "algorithm_id": "A5_pca_compact_hilbert",
                "bit_rule": "C3_frame_core_occupancy",
                "contamination_id": "D1",
                "geometry_id": "E1",
                "point_count": 128.0,
                "seed": 0.0,
                "kendall_tau_clean": 0.6,
            },
        ]
        h3 = h3_frame_stability(rows)
        self.assertEqual(h3["hypothesis"], "H3")
        self.assertFalse(h3["passed"])
        self.assertLess(h3["median_delta_rch_minus_baseline"], 0.0)

    def test_mean_ci_handles_empty_and_singleton(self) -> None:
        """mean_ci returns '' for empty and bare value for n=1."""
        self.assertEqual(mean_ci([]), "")
        self.assertEqual(mean_ci([1.5]), "1.5")

    def test_latex_escape_replaces_special_characters(self) -> None:
        """latex_escape escapes %, &, _, and \\."""
        self.assertEqual(latex_escape("a_b%c&d\\e"), "a\\_b\\%c\\&d\\textbackslash{}e")


if __name__ == "__main__":
    unittest.main()
