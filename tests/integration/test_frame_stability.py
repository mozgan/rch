#!/usr/bin/env python3
"""Short R2.1 natural -> matched quantizer -> independent inlier Kendall smoke."""
import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'analysis/scripts'))
from analyze_frame_stability import validate, digest


def read_ids(path):
    with path.open() as stream:
        return [int(r['raw_index']) for r in csv.DictReader(stream)]


def main():
    p = argparse.ArgumentParser(); p.add_argument('binary', type=Path); args = p.parse_args()
    binary = args.binary.resolve()
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='frame_stability_smoke_') as name:
        root = Path(name)
        spec = yaml.safe_load((ROOT / 'experiments/runlists/independent/frame_ablation_bit_rules.yaml').read_text())
        spec.update(name='frame_stability_smoke', geometry_ids=['E1'], point_counts=[32], seeds=[0, 1])
        spec['stability_control'].update(resolution_refinements=[0, 3], grid_shifts_cells=[0., .5])
        runlist = root / 'runlist.yaml'; runlist.write_text(yaml.safe_dump(spec))
        native = root / 'natural'
        command = [sys.executable, str(ROOT / 'experiments/runners/run_matrix.py'), '--runlist', str(runlist),
                   '--output-dir', str(native), '--rch-order-bin', str(binary), '--refinement', 'off']
        subprocess.run(command, check=True, capture_output=True, text=True)
        matched = root / 'matched'
        subprocess.run([sys.executable, str(ROOT / 'experiments/runners/run_frame_stability.py'),
            '--natural-results', str(native / 'frame_stability_smoke.csv'), '--runlist', str(runlist),
            '--rch-order-bin', str(binary), '--output-dir', str(matched)], check=True, capture_output=True, text=True)
        state, _, records = validate(matched)
        sample = next((native / 'manifests').glob('A6*.json'))
        meta = json.loads(sample.read_text())
        assert meta['robust_work_counts']['starts'] > 0
        assert meta['timing_breakdown_seconds']['robust_concentration'] > 0

        assert len(records) == 240
        for r in records:
            clean_name = r['order_file'].replace('__' + r['contamination_id'] + '__', '__D0__')
            n = int(r['clean_point_count'])
            clean = read_ids(matched / clean_name)
            order = [i for i in read_ids(matched / r['order_file']) if i < n]
            ranks = {id_: i for i, id_ in enumerate(clean)}
            inversions = sum(ranks[order[i]] > ranks[order[j]] for i in range(n) for j in range(i + 1, n))
            expected = 1 - 2 * inversions / (n * (n - 1) / 2)
            assert abs(expected - float(r['kendall_tau_clean'])) < 1e-14
        analyzer = [sys.executable, str(ROOT / 'analysis/scripts/analyze_frame_stability.py'),
                    '--input-root', str(matched), '--output-dir', str(root / 'report'),
                    '--artifact-root', str(root / 'artifacts'), '--bootstrap-resamples', '200']
        subprocess.run(analyzer, check=True, capture_output=True, text=True)
        assert (root / 'artifacts/figures/fig_frame_stability.pdf').is_file()
        subprocess.run(analyzer + ['--validate-only'], check=True, capture_output=True)
        with (root / 'artifacts/tables/table_frame_stability.tex').open('a') as stream:
            stream.write('changed artifact\n')
        assert subprocess.run(analyzer + ['--validate-only'], capture_output=True).returncode != 0
        # Changed numeric widths must fail even if a new CSV checksum is supplied.
        path = matched / 'frame_stability.csv'
        records[0]['cell_widths'] = json.dumps([1., 1., 1.])
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
        state['files_sha256'][path.name] = digest(path)
        (matched / 'run_manifest.json').write_text(json.dumps(state))
        try:
            validate(matched)
        except ValueError:
            pass
        else:
            raise AssertionError('unmatched resolution accepted')
        bad = subprocess.run([str(binary), '--input', str(next((native / 'data').glob('*.csv'))),
             '--method', 'rch', '--output', str(root / 'invalid.csv'), '--manifest', str(root / 'invalid.json'),
             '--fixed-frame-quantizer', '1,1,1,32,32,32'], capture_output=True)
        assert bad.returncode != 0
        for shift in ('nan', '2', '-2'):
            bad = subprocess.run([str(binary), '--input', str(next((native / 'data').glob('*.csv'))),
                '--method', 'rch', '--output', str(root / 'invalid.csv'), '--manifest', str(root / 'invalid.json'),
                '--fixed-frame-quantizer', '1,1,1,3,3,3', '--frame-grid-shift-cells', shift], capture_output=True)
            assert bad.returncode != 0
        print(json.dumps({'status': 'passed', 'natural_rows': 60, 'matched_rows': 240, 'independent_kendall_checks': 240}))


if __name__ == '__main__':
    main()
