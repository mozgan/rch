#!/usr/bin/env python3
"""Optional full-scene C1 resolution controls; never run by artifact readers.

Each method keeps its native C1 fitted center, axes and covering box. A replay
validates the fixed quantizer, an equal-budget arm redistributes bits, and depth
arms raise only the lowest-resolution axis. No inferred selector or p-value.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from analysis.scripts.analyze_c1_failure import digest, measure_order, write_rows
from experiments.runners.run_real_datasets import read_processed_points


def resolution_arms(bits: list[int]) -> dict[str, list[int]]:
    if len(bits) != 3 or any(type(b) is not int or not 1 <= b <= 32 for b in bits) or sum(bits) > 63:
        raise ValueError('invalid native bit allocation')
    total = sum(bits)
    balanced = [total // 3 + int(j < total % 3) for j in range(3)]
    arms = {'native_grid_replay': list(bits), 'equal_budget_balanced': balanced}
    axis = min(range(3), key=lambda j: bits[j])
    for depth in sorted({4, 7, 10}):
        if depth <= bits[axis]:
            continue
        refined = list(bits)
        refined[axis] = depth
        if sum(refined) <= 63:
            arms[f'raise_axis_{axis}_to_{depth}'] = refined
    arms['uniform_10'] = [10, 10, 10]
    return arms


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--real-root', type=Path, default=ROOT / 'experiments/outputs/real_dataset/off')
    p.add_argument('--output-dir', type=Path, default=ROOT / 'experiments/outputs/c1_resolution_ablation')
    p.add_argument('--dataset', action='append', choices=['stanford_bunny', 'stanford_armadillo', 'usgs_cameron_peak'])
    args = p.parse_args()
    binary, real_root, output = args.binary.resolve(), args.real_root.resolve(), args.output_dir.resolve()
    if output.exists():
        raise ValueError('output directory already exists; choose a fresh directory')
    binary_hash = digest(binary)
    datasets = args.dataset or ['stanford_bunny', 'stanford_armadillo']
    if len(set(datasets)) != len(datasets):
        raise ValueError('duplicate dataset')
    sources, jobs = {}, []
    for dataset in datasets:
        for algorithm in ('A5_pca_compact_hilbert', 'A6_rch'):
            path = real_root / 'manifests' / f'{dataset}__{algorithm}__C1_monotone_half__D0__s0.manifest.json'
            meta = json.loads(path.read_text())
            input_path = Path(meta['input'])
            input_path = input_path if input_path.is_absolute() else ROOT / input_path
            if meta.get('status') != 'ok' or meta.get('refinement') != 'off' or meta.get('bit_allocator') != 'monotone_half':
                raise ValueError('source cell is not native unrefined C1')
            if meta.get('controlled_frame_quantizer') or meta.get('fixed_frame_domain_half_extent', 0) != 0:
                raise ValueError('source cell already uses a controlled quantizer')
            for source in (path, input_path):
                sources[str(source.resolve())] = digest(source)
            jobs.append((dataset, algorithm, meta, input_path.resolve()))
    output.mkdir(parents=True)
    rows, commands = [], []
    for dataset, algorithm, recorded, input_path in jobs:
        points = np.asarray(read_processed_points(input_path), dtype=float)
        base = [str(binary), '--input', str(input_path), '--method', recorded['method'],
                '--frame-estimator', recorded['frame_estimator'], '--bit-allocator', 'monotone_half',
                '--uniform-bits', str(recorded['uniform_bits']), '--min-axis-bits', str(recorded['min_axis_bits']),
                '--refinement', 'off', '--timing-repeats', '1']
        native = None
        for arm in ['native_C1', *resolution_arms(recorded['bits_axis'])]:
            stem = f'{dataset}__{algorithm}__{arm}'
            order_path, meta_path = output / f'{stem}.order.csv', output / f'{stem}.manifest.json'
            command = [*base, '--output', str(order_path), '--manifest', str(meta_path)]
            if arm != 'native_C1':
                # Resolve arms from the freshly fitted native result, not stale source depths.
                arms = resolution_arms(native['bits_axis'])
                if arm not in arms:
                    raise ValueError('native bit allocation changed; start a new experiment protocol')
                quantizer = ','.join([*(format(x, '.17g') for x in native['frame_domain_half_extents']), *map(str, arms[arm])])
                command += ['--fixed-frame-quantizer', quantizer]
            print(f'[C1 control] {dataset}/{algorithm}/{arm}', flush=True)
            done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            (output / f'{stem}.log').write_text(done.stdout + done.stderr)
            commands.append(command)
            if done.returncode:
                raise RuntimeError(f'orderer failed; see {stem}.log')
            current = json.loads(meta_path.read_text())
            if current.get('status') != 'ok' or current.get('refinement') != 'off':
                raise ValueError('invalid orderer result')
            if arm == 'native_C1':
                native = current
            elif any(current[k] != native[k] for k in ('frame_center', 'frame_axes', 'frame_domain_half_extents')):
                raise ValueError('fixed-frame/domain intervention changed fitted geometry')
            if arm == 'native_grid_replay' and current['hash'] != native['hash']:
                raise ValueError('fixed quantizer does not reproduce the native C1 digest')
            measured = measure_order(points, order_path, current)
            if arm == 'native_C1':
                native_miad = measured['miad']
            rows.append(dict(dataset_id=dataset, algorithm_id=algorithm, arm=arm,
                delta_miad_vs_fresh_native=measured['miad'] - native_miad,
                fresh_native_matches_recorded=native['hash'] == recorded['hash'], **measured))
    if digest(binary) != binary_hash or any(digest(Path(p)) != h for p, h in sources.items()):
        raise ValueError('binary or source changed during experiment')
    write_rows(output / 'metrics.csv', rows)
    (output / 'scope.md').write_text(
        'Fixed real inputs; one native fitted frame per method, checked across all arms. '
        'Equal-budget balancing isolates a distribution change at fixed total bits; axis-depth arms change the budget. '
        'No bootstrap, population inference, timing comparison or deployable selection policy. '
        'Native replay must match its digest. New native results may differ from previous benchmark records.\n')
    (output / 'run_manifest.json').write_text(json.dumps(dict(schema='rch.c1_resolution_ablation.v1',
        binary_sha256=binary_hash, sources_sha256=sources, commands=commands,
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                       (Path(__file__).resolve(), ROOT / 'analysis/scripts/analyze_c1_failure.py')},
        files_sha256={p.name: digest(p) for p in output.iterdir() if p.is_file()}), indent=2) + '\n')


if __name__ == '__main__':
    main()
