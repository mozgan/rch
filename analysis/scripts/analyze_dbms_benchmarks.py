#!/usr/bin/env python3
"""Validate PostGIS benchmark matrices and publish within-DBMS paired evidence."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
from experiments.application_layouts import APPLICATION_OUTPUT_ROOT

BACKENDS = tuple(f'{layout}_{mode}' for layout in ('input', 'hilbert', 'rch') for mode in ('seq', 'ndgist'))


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def csv_rows(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plan_types(plan):
    yield plan['Node Type']
    for child in plan.get('Plans', []):
        yield from plan_types(child)


def validate(root):
    state = json.loads((root / 'run_manifest.json').read_text())
    if state.get('schema') != 'rch.dbms_benchmark.v1' or tuple(state['backends']) != BACKENDS or state['repeats'] < 1:
        raise ValueError('invalid DBMS protocol')
    if digest(root / 'source_manifest.json') != state['source_manifest_sha256']:
        raise ValueError('invalid source snapshot')
    repository = Path(__file__).resolve().parents[2]
    for source_path, checksum in state.get("source_sha256", {}).items():
        target = (repository / source_path).resolve()
        target.relative_to(repository)
        if digest(target) != checksum:
            raise ValueError(f"benchmark source changed: {source_path}; rerun the benchmark")
    for name, checksum in state['files_sha256'].items():
        path = (root / name).resolve()
        path.relative_to(root.resolve())
        if digest(path) != checksum:
            raise ValueError(f'checksum mismatch: {name}')
    if not state['datasets'] or len({d['dataset_id'] for d in state['datasets']}) != len(state['datasets']):
        raise ValueError('invalid dataset matrix')
    groups = {}
    diagnostics = []
    for d in state['datasets']:
        id_ = d['dataset_id']
        queries = set(d['query_ids'])
        if len(queries) != state['queries_per_dataset'] or len(d['query_ids']) != len(queries):
            raise ValueError('invalid query inventory')
        for suffix in ('metrics.csv', 'plans.jsonl', 'oracle.json'):
            if f'{id_}.{suffix}' not in state['files_sha256']:
                raise ValueError('required file absent from inventory')
        oracle = json.loads((root / f'{id_}.oracle.json').read_text())
        if set(oracle) != queries:
            raise ValueError('oracle query mismatch')
        rows = csv_rows(root / f'{id_}.metrics.csv')
        seen = set()
        for r in rows:
            key = r['backend'], int(r['block']), r['query_id']
            if key in seen or key[0] not in BACKENDS or not 0 <= key[1] < state['repeats'] or key[2] not in queries:
                raise ValueError('duplicate/unexpected DBMS row')
            seen.add(key)
            if r['dataset_id'] != id_ or r['oracle_match'] != 'true' or [int(r['result_count']), r['result_hash']] != oracle[key[2]]:
                raise ValueError('oracle mismatch')
            timing = float(r['client_wall_seconds'])
            if not math.isfinite(timing) or timing <= 0:
                raise ValueError('invalid client wall time')
        expected = {(b, block, q) for b in BACKENDS for block in range(state['repeats']) for q in queries}
        if seen != expected:
            raise ValueError('incomplete DBMS matrix')
        for backend in BACKENDS:
            groups[id_, backend] = [r for r in rows if r['backend'] == backend]
        plans_seen = set()
        with (root / f'{id_}.plans.jsonl').open() as handle:
            for line in handle:
                p = json.loads(line)
                key = p['backend'], p['query_id']
                if key in plans_seen or key[0] not in BACKENDS or key[1] not in queries:
                    raise ValueError('duplicate/unexpected diagnostic plan')
                plans_seen.add(key)
                doc = p['document']
                if doc['Plan']['Actual Rows'] != oracle[key[1]][0]:
                    raise ValueError('plan result count mismatch')
                types = list(plan_types(doc['Plan']))
                index_used = any('Index' in t or 'Bitmap' in t for t in types)
                if key[0].endswith('_seq') and index_used:
                    raise ValueError('sequential arm used an index')
                diagnostics.append({'dataset_id': id_, 'backend': key[0], 'query_id': key[1],
                                    'server_execution_seconds': doc['Execution Time'] / 1000,
                                    'server_planning_seconds': doc['Planning Time'] / 1000,
                                    'index_used': index_used, 'node_types': ';'.join(types),
                                    'shared_hit_blocks': doc['Plan'].get('Shared Hit Blocks'),
                                    'shared_read_blocks': doc['Plan'].get('Shared Read Blocks'),
                                    'scope': 'separate EXPLAIN ANALYZE diagnostic execution; not timed client run'})
        if plans_seen != {(b, q) for b in BACKENDS for q in queries}:
            raise ValueError('incomplete plan matrix')
    return state, groups, diagnostics


def analyze(root, output, artifact_root=None):
    state, groups, diagnostics = validate(root)
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for (id_, backend), rows in groups.items():
        d = next(d for d in state['datasets'] if d['dataset_id'] == id_)
        layout, mode = backend.rsplit('_', 1)
        prep = next(p for p in d['layouts'] if p['layout'] == layout)
        times = [float(r['client_wall_seconds']) for r in rows]
        plans = [p for p in diagnostics if p['dataset_id'] == id_ and p['backend'] == backend]
        summary.append({'dataset_id': id_, 'backend': backend, 'rows': len(rows),
                        'mean_client_wall_seconds': statistics.fmean(times),
                        'p50_client_wall_seconds': float(np.quantile(times, .5)),
                        'p95_client_wall_seconds': float(np.quantile(times, .95)),
                        'p99_client_wall_seconds': float(np.quantile(times, .99)),
                        'load_seconds': prep['load_seconds'], 'index_seconds': prep['index_seconds'],
                        'vacuum_analyze_seconds': prep['vacuum_analyze_seconds'],
                        'table_bytes': prep['table_bytes'], 'index_bytes': prep['index_bytes'],
                        'diagnostic_index_query_count': sum(p['index_used'] for p in plans),
                        'diagnostic_mean_server_execution_seconds': statistics.fmean(p['server_execution_seconds'] for p in plans)})
    paired = []
    rng = np.random.default_rng(20261105)
    comparisons = [('input_ndgist', 'input_seq'), ('hilbert_ndgist', 'input_ndgist'), ('rch_ndgist', 'input_ndgist'),
                   ('rch_ndgist', 'hilbert_ndgist'), ('hilbert_seq', 'input_seq'), ('rch_seq', 'input_seq')]
    for d in state['datasets']:
        id_ = d['dataset_id']
        for backend, reference in comparisons:
            ref = {(r['query_id'], r['block']): float(r['client_wall_seconds']) for r in groups[id_, reference]}
            deltas = defaultdict(list)
            for r in groups[id_, backend]:
                deltas[r['query_id']].append(float(r['client_wall_seconds']) - ref[r['query_id'], r['block']])
            values = np.array([statistics.fmean(v) for _, v in sorted(deltas.items())])
            means = np.mean(rng.choice(values, size=(10000, len(values))), axis=1)
            paired.append({'dataset_id': id_, 'backend': backend, 'reference': reference,
                           'mean_delta_seconds': float(np.mean(values)), 'ci95_low_seconds': float(np.quantile(means, .025)),
                           'ci95_high_seconds': float(np.quantile(means, .975)), 'query_count': len(values),
                           'scope': 'same DBMS; descriptive query bootstrap, repeated blocks averaged; unadjusted intervals'})
    write_csv(output / 'summary.csv', summary)
    write_csv(output / 'paired_comparisons.csv', paired)
    write_csv(output / 'plan_metrics.csv', diagnostics)
    (output / 'evidence.md').write_text(
        '# DBMS benchmark evidence\n\nPostgreSQL/PostGIS point tables use input, Hilbert and RCH COPY insertion orders. '
        'Each has a forced sequential-scan arm and a 3D ND GiST candidate-filter arm with exact inclusive XYZ recheck. '
        'Indexed arms allow planner-selected sequential scans, reported in plan_metrics.csv. '
        'Client wall includes SQL planning/execution, ID sorting/transport/decoding/materialization; hashing/oracle are outside. '
        'Server execution and buffer counters come from separate EXPLAIN ANALYZE diagnostic passes. '
        'Shared buffer reads are not physical device I/O. Workload warmup does not guarantee all data resides in cache. '
        'Load/index/vacuum times exclude prior SFC ordering. No total preparation break-even, server RSS, '
        'cold-cache, general DBMS superiority or HistSFC/SplitSFC/pgPointCloud replication is claimed. '
        'Bootstrap intervals are within each fixed dataset, not independent-scene inference.\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ids = [d['dataset_id'] for d in state['datasets']]
    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    x = np.arange(len(ids))
    for j, backend in enumerate(BACKENDS):
        values = [next(r['mean_client_wall_seconds'] for r in summary if r['dataset_id'] == id_ and r['backend'] == backend) * 1000 for id_ in ids]
        ax.bar(x + (j - 2.5) * .13, values, width=.12, label=backend)
    ax.set_xticks(x, ids, rotation=20, ha='right')
    ax.set_ylabel('Mean client query wall time (ms)')
    ax.legend(fontsize=7)
    fig.savefig(output / 'fig_dbms_query_latency.pdf')
    plt.close(fig)
    lines = [r'\begin{tabular}{llr}', r'Dataset & Backend & Mean query (ms) \\', r'\hline']
    for r in summary:
        lines.append(r['dataset_id'].replace('_', r'\_') + ' & ' + r['backend'].replace('_', r'\_') + f" & {r['mean_client_wall_seconds'] * 1000:.4f}" + r' \\')
    lines.append(r'\end{tabular}')
    (output / 'table_dbms_query.tex').write_text('\n'.join(lines) + '\n')
    published = {}
    if artifact_root:
        import shutil
        for subdir, name in [('figures', 'fig_dbms_query_latency.pdf'), ('tables', 'table_dbms_query.tex')]:
            (artifact_root / subdir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output / name, artifact_root / subdir / name)
            published[str(Path(subdir) / name)] = digest(artifact_root / subdir / name)
    files = [p for p in output.iterdir() if p.is_file() and p.name != 'analysis_manifest.json']
    (output / 'analysis_manifest.json').write_text(json.dumps({'status': 'validated_dbms_matrix',
        'source_manifest_sha256': digest(root / 'run_manifest.json'),
        'artifacts': {p.name: digest(p) for p in files}, 'published_artifacts': published}, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--artifact-root', type=Path)
    p.add_argument('--application-root', type=Path, default=REPOSITORY_ROOT / APPLICATION_OUTPUT_ROOT)
    p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    if a.application_root:
        state = json.loads((a.input_root / 'run_manifest.json').read_text())
        if state['source_manifest_sha256'] != digest(a.application_root / 'run_manifest.json'):
            raise ValueError('DBMS benchmark belongs to another application run')
    if a.validate_only:
        validate(a.input_root)
        if a.output_dir:
            manifest = json.loads((a.output_dir / 'analysis_manifest.json').read_text())
            if manifest['source_manifest_sha256'] != digest(a.input_root / 'run_manifest.json'):
                raise ValueError('stale DBMS analysis')
            for name, checksum in manifest['artifacts'].items():
                if digest(a.output_dir / name) != checksum:
                    raise ValueError('stale analysis artifact')
            if a.artifact_root:
                if not manifest['published_artifacts']:
                    raise ValueError('DBMS published artifacts missing')
                for name, checksum in manifest['published_artifacts'].items():
                    if digest(a.artifact_root / name) != checksum:
                        raise ValueError('stale published artifact')
        print('DBMS inventory, matrix, oracle and plans verified')
    else:
        analyze(a.input_root, a.output_dir or a.input_root / 'analysis', a.artifact_root)


if __name__ == '__main__':
    main()
