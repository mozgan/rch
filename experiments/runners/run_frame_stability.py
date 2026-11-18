#!/usr/bin/env python3
"""R2.1: frozen-resolution replay of the natural frame x rule contamination factorial."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/runners'))
from run_matrix import read_order_csv, kendall_tau_against_clean, is_permutation_of_size
FRAMES = ('A5_pca_compact_hilbert', 'A6_rch')
RULES = ('C2_occupancy_floor1', 'C3_frame_core_occupancy', 'C4_hybrid')


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def stem(row):
    return f"{row['algorithm_id']}__{row['bit_rule']}__{row['contamination_id']}__{row['geometry_id']}__n{row['clean_point_count']}__s{row['seed']}"


def run(args):
    spec = yaml.safe_load(args.runlist.read_text())
    if len(spec['point_counts']) != 1:
        raise ValueError('this protocol uses one point count; nested sample sizes must not be counted as independent clouds')
    control = spec['stability_control']
    if control['schema'] != 'rch.frame_stability_control.v1' or control['depth_reference'] != 'paired_clean_max':
        raise ValueError('unsupported stability control')
    levels = control['resolution_refinements']
    if not levels or len(set(levels)) != len(levels) or any(type(x) is not int or not 0 <= x <= 8 for x in levels):
        raise ValueError('invalid resolution refinements')
    shifts = control.get('grid_shifts_cells', [0.0])
    if not shifts or len(set(shifts)) != len(shifts) or any(not math.isfinite(x) or abs(x) > 1 for x in shifts):
        raise ValueError('invalid grid origin shifts')
    conditions = control['expected_contaminations']
    if conditions[0] != 'D0' or set(conditions) != set(spec['contamination_ids']) or len(set(conditions)) != len(conditions):
        raise ValueError('D0 baseline and exact conditions required')
    with args.natural_results.open() as handle:
        rows = list(csv.DictReader(handle))
    blocks = defaultdict(dict)
    expected_blocks = {(g, n, s) for g in spec['geometry_ids'] for n in spec['point_counts'] for s in spec['seeds']}
    source_root = args.natural_results.parent
    for row in rows:
        if row['refinement'] != 'off' or not row['kendall_tau_clean']:
            raise ValueError('natural rows require refinement off and measured Kendall')
        block = row['geometry_id'], int(row['clean_point_count']), int(row['seed'])
        key = row['algorithm_id'], row['bit_rule'], row['contamination_id']
        if key in blocks[block]:
            raise ValueError('duplicate natural factorial row')
        name = stem(row)
        manifest_path = source_root / 'manifests' / (name + '.manifest.json')
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('controlled_frame_quantizer', False) or manifest.get('fixed_frame_domain_half_extent', 0) != 0:
            raise ValueError('natural factorial must use unmodified quantizers')
        if manifest['status'] != 'ok' or manifest['hash'] != row['output_hash'] or manifest['bits_axis'] != [int(x) for x in row['bits_axis'].split()] or manifest['point_count'] != int(row['point_count']):
            raise ValueError('natural CSV and C++ manifest disagree')
        blocks[block][key] = row, manifest, source_root / 'data' / (name + '.csv'), manifest_path
    if set(blocks) != expected_blocks:
        raise ValueError('natural cloud matrix incomplete')
    expected_cells = {(a, r, d) for a in FRAMES for r in RULES for d in conditions}
    if any(set(cells) != expected_cells for cells in blocks.values()):
        raise ValueError('natural 2x3 contamination block incomplete')
    if args.output_dir.exists():
        raise ValueError('controlled output exists; choose a new output directory')
    args.output_dir.mkdir(parents=True)
    (args.output_dir / 'runlist.yaml').write_bytes(args.runlist.read_bytes())
    (args.output_dir / 'natural_results.csv').write_bytes(args.natural_results.read_bytes())
    provenance = {'schema': 'rch.frame_stability.v1', 'runlist_sha256': sha(args.runlist),
                  'natural_results_sha256': sha(args.natural_results), 'binary_sha256': sha(args.rch_order_bin),
                  'resolution_refinements': levels, 'grid_shifts_cells': shifts, 'conditions': conditions, 'blocks': [], 'files_sha256': {},
                  'natural_manifest_sha256': {str(path.relative_to(source_root)): sha(path)
                      for cells in blocks.values() for _, _, _, path in cells.values()},
                  'interpretation': 'Controlled intervention: all six arms and conditions share cell widths. Domain/depth are frozen within each rule; native policies are reported separately. Center and axes both vary with frame estimator.'}
    output_rows = []
    for block, cells in sorted(blocks.items()):
        # Ensure identical clean/inlier and outlier inputs within every factorial cell.
        input_hashes = {}
        for condition in conditions:
            hashes = {sha(cells[a, r, condition][2]) for a in FRAMES for r in RULES}
            if len(hashes) != 1:
                raise ValueError('factorial arms do not share identical cloud input')
            input_hashes[condition] = hashes.pop()
            for algorithm in FRAMES:
                for rule in RULES:
                    native_row = cells[algorithm, rule, condition][0]
                    native_order = read_order_csv(source_root / 'orders' / (stem(native_row) + '.order.csv'))
                    clean_row = cells[algorithm, rule, 'D0'][0]
                    clean_order = read_order_csv(source_root / 'orders' / (stem(clean_row) + '.order.csv'))
                    if not is_permutation_of_size(native_order, int(native_row['point_count'])) or not is_permutation_of_size(clean_order, block[1]):
                        raise ValueError('invalid natural permutation')
                    native_tau = kendall_tau_against_clean(clean_order, native_order, block[1])
                    if not math.isclose(native_tau, float(native_row['kendall_tau_clean']), abs_tol=1e-14):
                        raise ValueError('natural Kendall baseline mismatch')
        depth = {r: [max(cells[a, r, 'D0'][1]['bits_axis'][j] for a in FRAMES) for j in range(3)] for r in RULES}
        for bits in depth.values():
            if any(not 1 <= b <= 32 or b + max(levels) > 32 for b in bits) or sum(bits) + 3 * max(levels) > 63:
                raise ValueError('controlled depth budget exceeded; revise protocol before running')
        widths = [max(math.ldexp(float(cells[a, r, d][1]['frame_domain_half_extents'][j]), 1 - depth[r][j])
                      for a in FRAMES for r in RULES for d in conditions) for j in range(3)]
        if any(not math.isfinite(x) or x <= 0 for x in widths):
            raise ValueError('invalid shared cell width')
        half = {r: [math.ldexp(widths[j], depth[r][j] - 1) for j in range(3)] for r in RULES}
        provenance['blocks'].append({'geometry': block[0], 'clean_count': block[1], 'seed': block[2],
                                     'base_cell_widths': widths, 'depths': depth, 'half_extents': half, 'input_hashes': input_hashes, 'input_files': {}})
        clean_points = None
        for d in conditions:
            sample = cells[FRAMES[0], RULES[0], d][2].read_text().splitlines()
            if d == 'D0':
                clean_points = sample
            if sample[:block[1]] != clean_points or len(clean_points) != block[1]:
                raise ValueError('contamination does not preserve original inlier IDs')
            if any(int(cells[a, r, d][0]['point_count']) != len(sample) for a in FRAMES for r in RULES):
                raise ValueError('natural point-count mismatch')
        # Encoding-free raw-coordinate tie-break control and portable source snapshots.
        tie_orders, tie_files = {}, {}
        for condition in conditions:
            src = cells[FRAMES[0], RULES[0], condition][2]
            tag = f"{block[0]}__n{block[1]}__s{block[2]}__{condition}"
            snapshot = args.output_dir / (tag + '.input.csv')
            snapshot.write_bytes(src.read_bytes())
            provenance['blocks'][-1]['input_files'][condition] = snapshot.name
            points = [tuple(map(float, r)) for r in csv.reader(src.open())]
            order = sorted(range(len(points)), key=lambda i: (*points[i], i))
            tie_orders[condition] = order
            tie_file = args.output_dir / (tag + '.raw_tie.order.csv')
            with tie_file.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(['raw_index']); writer.writerows((i,) for i in order)
            tie_files[condition] = tie_file.name
            if kendall_tau_against_clean(tie_orders['D0'], order, block[1]) != 1.0:
                raise ValueError('raw tie-break inlier stability must be one')
        for level, shift in ((level, shift) for level in levels for shift in shifts):
            baseline = {}
            for condition in conditions:
                for algorithm in FRAMES:
                    for rule in RULES:
                        row, natural, input_path, _ = cells[algorithm, rule, condition]
                        bits = [b + level for b in depth[rule]]
                        quantizer = ','.join([*(format(x, '.17g') for x in half[rule]), *map(str, bits)])
                        name = stem(row) + f'__resolution{level}' + (f'__shift{shift:g}' if shift else '')
                        order_path = args.output_dir / (name + '.order.csv')
                        manifest_path = args.output_dir / (name + '.manifest.json')
                        command = [str(args.rch_order_bin), '--input', str(input_path), '--method', row['method'],
                                   '--frame-estimator', row['frame_estimator'], '--bit-allocator', row['bit_allocator'],
                                   '--refinement', 'off', '--fixed-frame-quantizer', quantizer, '--frame-grid-shift-cells', str(shift),
                                   '--output', str(order_path), '--manifest', str(manifest_path)]
                        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                        if completed.returncode:
                            log = args.output_dir / (name + '.error.log')
                            log.write_text(completed.stdout + completed.stderr)
                            raise RuntimeError(f'controlled CLI failed; see {log}')
                        natural_snapshot = args.output_dir / (stem(row) + '.natural.manifest.json')
                        if not natural_snapshot.exists():
                            natural_snapshot.write_bytes(cells[algorithm, rule, condition][3].read_bytes())
                        actual = json.loads(manifest_path.read_text())
                        if actual['frame_center'] != natural['frame_center'] or actual['frame_axes'] != natural['frame_axes'] or actual['robust_fallback_used'] != natural['robust_fallback_used']:
                            raise ValueError('quantizer intervention changed the fitted frame')
                        axes = actual['frame_axes']
                        for j in range(3):
                            for k in range(3):
                                dot = sum(axes[j][i] * axes[k][i] for i in range(3))
                                if not math.isclose(dot, float(j == k), abs_tol=1e-9):
                                    raise ValueError('frame is not orthonormal: cell widths are not physical lengths')
                        order = read_order_csv(order_path)
                        if not is_permutation_of_size(order, int(row['point_count'])):
                            raise ValueError('invalid controlled permutation')
                        if not actual.get('controlled_frame_quantizer') or actual['bits_axis'] != bits or actual['frame_domain_half_extents'] != half[rule]:
                            raise ValueError('C++ did not apply frozen quantizer')
                        if condition == 'D0':
                            baseline[algorithm, rule] = order
                        tau = kendall_tau_against_clean(baseline[algorithm, rule], order, block[1])
                        output_rows.append({'geometry_id': block[0], 'clean_point_count': block[1], 'seed': block[2],
                            'algorithm_id': algorithm, 'bit_rule': rule, 'contamination_id': condition, 'resolution': level, 'grid_shift_cells': shift,
                            'input_file': provenance['blocks'][-1]['input_files'][condition],
                            'natural_manifest_file': natural_snapshot.name,
                            'tie_break_order_file': tie_files[condition],
                            'kendall_vs_raw_tie_break': kendall_tau_against_clean(tie_orders[condition], order, int(row['point_count'])),
                            'point_count': actual['point_count'], 'order_file': order_path.name, 'manifest_file': manifest_path.name,
                            'kendall_tau_clean': tau, 'bits_axis': json.dumps(bits), 'half_extents': json.dumps(half[rule]),
                            'cell_widths': json.dumps([math.ldexp(x, -level) for x in widths]),
                            'input_sha256': input_hashes[condition], 'output_hash': actual['hash'],
                            'robust_fallback_used': actual['robust_fallback_used'],
                            'quantization_diagnostics': json.dumps(actual['quantization_diagnostics'], sort_keys=True)})
        print(f'[frame-stability] {block} controlled replay complete', flush=True)
    with (args.output_dir / 'frame_stability.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader(); writer.writerows(output_rows)
    if sha(args.rch_order_bin) != provenance['binary_sha256'] or sha(args.natural_results) != provenance['natural_results_sha256']:
        raise ValueError('binary/natural source changed during replay')
    for path in args.output_dir.iterdir():
        if path.is_file():
            provenance['files_sha256'][path.name] = sha(path)
    (args.output_dir / 'run_manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--natural-results', type=Path, required=True)
    p.add_argument('--runlist', type=Path, required=True)
    p.add_argument('--rch-order-bin', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args(); a.rch_order_bin = a.rch_order_bin.resolve(); run(a)


if __name__ == '__main__':
    main()
