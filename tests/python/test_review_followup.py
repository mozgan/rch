"""Fast, fixture-only regression tests for reviewer follow-up diagnostics."""
import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from analysis.scripts.analyze_c1_failure import measure_order
from analysis.scripts.legacy_claims import annotate_legacy_statistics, claim_status_rows
from experiments.runners.run_c1_resolution_ablation import resolution_arms

ROOT = Path(__file__).resolve().parents[2]
ORDERER = Path(os.environ.get('RCH_ORDER_BIN', ROOT / 'build/bench/src/cli/rch_order')).resolve()


class LegacyInterpretationTests(unittest.TestCase):
    def test_nominal_pass_cannot_confirm_or_override_observed_direction(self):
        stats = {'hypotheses': [dict(hypothesis='H1', n_pairs=30, passed=True,
                 p_adj=.001, median_delta_rch_minus_baseline=.5, alternative='less')]}
        status = claim_status_rows(stats, {})[0]
        self.assertEqual(status['status'], 'Unfavorable direction (descriptive)')
        self.assertIn('nominal', status['evidence'])

    def test_missing_or_nonfinite_effect_is_not_assessed(self):
        for delta in (None, float('nan'), float('inf')):
            stats = {'hypotheses': [dict(hypothesis='H1', n_pairs=30, passed=True,
                     median_delta_rch_minus_baseline=delta)]}
            self.assertEqual(claim_status_rows(stats, {})[0]['status'], 'Not assessed')

    def test_metadata_preserves_historical_numbers_and_flags(self):
        original = dict(hypotheses=[dict(hypothesis='H1', p=.002, passed=True)],
                        stratified_by_bit_rule=[dict(hypothesis='H1', p=.02, passed=False)],
                        definition_of_done_passed=True)
        result = copy.deepcopy(original)
        annotate_legacy_statistics(result)
        for field in ('hypotheses', 'stratified_by_bit_rule'):
            for old, new in zip(original[field], result[field]):
                self.assertTrue(all(new[k] == v for k, v in old.items()))
        self.assertTrue(result['definition_of_done_passed'])
        self.assertFalse(result['definition_of_done_is_calibrated_inference'])
        self.assertNotIn('genuinely independent', result['stratified_scope'])


class C1DiagnosticsTests(unittest.TestCase):
    def fixture(self, directory, ids=(0, 1, 2)):
        path = Path(directory) / 'order.csv'
        with path.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['rank', 'raw_index', 'key'])
            writer.writerows((rank, i, key) for rank, (i, key) in enumerate(zip(ids, (1, 1, 2))))
        return path

    def test_path_decomposition_and_point_vs_edge_collision_fractions(self):
        with tempfile.TemporaryDirectory() as directory:
            points = np.array([[0, 0, 0], [3, 0, 0], [3, 4, 0]], dtype=float)
            result = measure_order(points, self.fixture(directory),
                dict(bits_axis=[10, 4, 1], frame_domain_half_extents=[1, 1, 1]))
            self.assertEqual(result['miad'], 3.5)
            self.assertEqual(result['within_key_miad_contribution'], 1.5)
            self.assertEqual(result['cross_key_miad_contribution'], 2)
            self.assertEqual(result['shared_key_point_fraction'], 2 / 3)
            self.assertEqual(result['same_key_edge_fraction'], .5)
            self.assertEqual(result['clipped_point_fraction'], '')

    def test_invalid_permutation_and_stored_collision_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            points = np.zeros((3, 3))
            meta = dict(bits_axis=[5, 5, 5], frame_domain_half_extents=[1, 1, 1])
            with self.assertRaisesRegex(ValueError, 'permutation'):
                measure_order(points, self.fixture(directory, ids=(0, 0, 2)), meta)
            meta['quantization_diagnostics'] = {'duplicate_hilbert_key_point_count': 0}
            with self.assertRaisesRegex(ValueError, 'shared-key'):
                measure_order(points, self.fixture(directory), meta)

    def test_equal_budget_control_and_axis_only_controls(self):
        arms = resolution_arms([10, 4, 1])
        self.assertEqual(sum(arms['equal_budget_balanced']), 15)
        self.assertEqual(arms['equal_budget_balanced'], [5, 5, 5])
        self.assertEqual(arms['raise_axis_2_to_7'], [10, 4, 7])
        self.assertEqual(arms['native_grid_replay'], [10, 4, 1])
        self.assertEqual(arms['uniform_10'], [10, 10, 10])

    @unittest.skipUnless(ORDERER.is_file(), 'prebuilt orderer unavailable; no build is launched')
    def test_fixed_frame_runner_on_32_point_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / 'real'
            (real / 'manifests').mkdir(parents=True)
            xyz = np.random.default_rng(1907).normal(size=(32, 3)) * [5, 2, .5]
            points = root / 'points.ply'
            points.write_text('ply\nformat ascii 1.0\nelement vertex 32\nproperty double x\n'
                'property double y\nproperty double z\nend_header\n' +
                '\n'.join(' '.join(format(x, '.17g') for x in row) for row in xyz) + '\n')
            for algorithm, method, frame in (
                ('A5_pca_compact_hilbert', 'pca_compact_hilbert', 'sample_covariance'),
                ('A6_rch', 'rch', 'det_mcd')):
                meta_path = real / 'manifests' / f'stanford_bunny__{algorithm}__C1_monotone_half__D0__s0.manifest.json'
                subprocess.run([str(ORDERER), '--input', str(points), '--output', str(root / f'{algorithm}.csv'),
                    '--manifest', str(meta_path), '--method', method, '--frame-estimator', frame,
                    '--bit-allocator', 'monotone_half', '--refinement', 'off'],
                    check=True, capture_output=True, text=True, timeout=5)
            output = root / 'controls'
            subprocess.run([sys.executable, str(ROOT / 'experiments/runners/run_c1_resolution_ablation.py'),
                '--binary', str(ORDERER), '--real-root', str(real), '--output-dir', str(output),
                '--dataset', 'stanford_bunny'], check=True, capture_output=True, text=True, timeout=10)
            with (output / 'metrics.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 14)
            for row in rows:
                self.assertEqual(row['fresh_native_matches_recorded'], 'True')
                if row['arm'] == 'native_grid_replay':
                    self.assertEqual(float(row['delta_miad_vs_fresh_native']), 0)
                if row['arm'] == 'equal_budget_balanced':
                    self.assertEqual(json.loads(row['bits_axis']), [5, 5, 5])


if __name__ == '__main__':
    unittest.main()
