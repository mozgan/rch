"""Exercise distinct fallback mechanisms through the existing ordering executable."""
import argparse
import csv
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    cases = [
        ('small_tetrahedron', [[0,0,0],[1,0,0],[0,2,0],[0,0,4]], 'det_mcd', True, 'principal_eigenframe'),
        ('collinear', [[t,2*t,-.5*t] for t in range(30)], 'det_mcd', True, 'canonical_axes_fallback'),
        ('coplanar', [[i%10,i//10,2*(i%10)-(i//10)] for i in range(30)], 'det_mcd', True, 'principal_eigenframe'),
        ('identical', [[1,2,3]]*24, 'det_mcd', True, 'canonical_axes_fallback'),
        ('isotropic_sample_control', [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]], 'sample', False, 'canonical_axes_fallback'),
        ('full_rank', (np.random.default_rng(11).normal(size=(80,3))*[1,2,5]).tolist(), 'det_mcd', False, 'principal_eigenframe'),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix='fallback_cli_') as directory:
        root = Path(directory)
        for name, points, estimator, expected_flag, expected_mode in cases:
            xyz = np.asarray(points, dtype=float)
            source = root / (name + '.csv')
            np.savetxt(source, xyz, delimiter=',', fmt='%.17g')
            for allocator in ['occupancy_floor1', 'frame_core_occupancy', 'hybrid_occupancy']:
                repeated = []
                for repetition in range(2):
                    output = root / f'{name}_{allocator}_{repetition}.csv'
                    metadata = output.with_suffix('.json')
                    command = [str(binary), '--input', str(source), '--output', str(output),
                               '--manifest', str(metadata), '--method', 'rch',
                               '--frame-estimator', estimator, '--bit-allocator', allocator,
                               '--refinement', 'off']
                    run = subprocess.run(command, capture_output=True, text=True)
                    if run.returncode:
                        raise AssertionError(f'{name}/{allocator}: {run.stderr}')
                    state = json.loads(metadata.read_text())
                    with output.open() as stream:
                        ordered = list(csv.DictReader(stream))
                    order = [int(row['raw_index']) for row in ordered]
                    assert sorted(order) == list(range(len(xyz))), 'lost/duplicated point IDs'
                    assert state['robust_fallback_used'] is expected_flag
                    assert state['fitted_frame_diagnostics']['mode'] == expected_mode
                    center = np.asarray(state['frame_center'])
                    axes = np.asarray(state['frame_axes'])
                    assert np.all(np.isfinite(center)) and np.all(np.isfinite(axes))
                    assert np.allclose(axes.T @ axes, np.eye(3), atol=1e-10)
                    if expected_flag:
                        assert np.allclose(center, xyz.mean(axis=0), atol=1e-12)
                    if expected_mode == 'canonical_axes_fallback':
                        assert np.array_equal(axes, np.eye(3))
                    if name == 'identical':
                        assert order == list(range(len(xyz)))
                    repeated.append((state['hash'], order))
                assert repeated[0] == repeated[1], 'unstable digest/permutation on repeated input'
                results.append({'case': name, 'points': len(points), 'estimator': estimator,
                                'allocator': allocator, 'estimator_fallback': expected_flag,
                                'frame_mode': expected_mode, 'input_sha256': digest(source),
                                'output_hash': repeated[0][0], 'repeated_orders_equal': True})
        # Empty input is accepted, with an empty permutation and fallback metadata.
        source = root / 'empty.csv'
        source.write_text('')
        output = root / 'empty.order.csv'
        metadata = root / 'empty.manifest.json'
        run = subprocess.run([str(binary), '--input', str(source), '--output', str(output),
                              '--manifest', str(metadata)], capture_output=True, text=True)
        assert run.returncode == 0
        empty = json.loads(metadata.read_text())
        assert empty['point_count'] == 0
        assert empty['robust_fallback_used'] is True
        assert empty['fitted_frame_diagnostics']['mode'] == 'canonical_axes_fallback'
        with output.open() as stream:
            assert list(csv.DictReader(stream)) == []
        rejections = []
        for name, contents in [('nan', '0,0,nan\n'), ('positive_inf', '0,0,inf\n'),
                               ('negative_inf', '0,0,-inf\n'), ('malformed', '0,not_a_number,0\n'),
                               ('finite_input_overflow', '1e308,1e308,1e308\n' * 4)]:
            source = root / (name + '.csv')
            source.write_text(contents)
            output = root / (name + '.order.csv')
            metadata = root / (name + '.manifest.json')
            run = subprocess.run([str(binary), '--input', str(source), '--output', str(output),
                                  '--manifest', str(metadata)], capture_output=True, text=True)
            assert run.returncode != 0 and not metadata.exists(), 'invalid input accepted as successful evidence'
            if name == 'finite_input_overflow':
                assert 'non-finite frame geometry' in run.stderr
                assert not output.exists(), 'numeric failure published a partial order'
            rejections.append({'case': name, 'returncode': run.returncode, 'successful_manifest_created': False})
    result = {'status': 'passed', 'binary_sha256': digest(binary),
              'test_sha256': digest(Path(__file__)), 'ordering_cases': len(results),
              'cli_ordering_calls': len(results)*2, 'invalid_input_cases': len(rejections),
              'empty_input_case': 'passed; empty permutation, estimator and canonical-axis fallback metadata',
              'scope': 'constructed short boundary controls; not benchmark frequency or population robustness evidence',
              'cases': results, 'rejections': rejections}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['status','ordering_cases','cli_ordering_calls','invalid_input_cases']}))


if __name__ == '__main__':
    main()
