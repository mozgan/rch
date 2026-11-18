#!/usr/bin/env python3
"""Exact 3D PostgreSQL/PostGIS benchmark using frozen application inputs."""
from __future__ import annotations
import argparse
import contextlib
import csv
import hashlib
import json
import os
import platform
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import psycopg
from psycopg import sql
from dbms_backend import (BACKENDS, LAYOUTS, managed_server, connect, server_info,
                          create_table, table_name, query_statement, parameters, configure_scan, nodes)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analysis/scripts'))
from analyze_dbms_benchmarks import analyze, digest
from experiments.application_layouts import APPLICATION_OUTPUT_ROOT


def frozen(path, checksum):
    p = (ROOT / path).resolve()
    p.relative_to(ROOT)
    if digest(p) != checksum:
        raise ValueError(f'source checksum mismatch: {path}')
    return p


def id_hash(ids) -> str:
    return hashlib.sha256(np.asarray(ids, dtype='<u8').tobytes()).hexdigest()


def read_order(path, count):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    if [int(r['rank']) for r in rows] != list(range(count)):
        raise ValueError('invalid source order ranks')
    ids = np.array([int(r['raw_index']) for r in rows], dtype=np.int64)
    if len(ids) != count or not np.array_equal(np.sort(ids), np.arange(count)):
        raise ValueError('invalid source order permutation')
    return ids


def load_inputs(args):
    path = args.source_root / 'run_manifest.json'
    source = json.loads(path.read_text())
    from experiments.application_layouts import is_application_source
    if not is_application_source(source):
        raise ValueError('expected shared application query manifest; run make app-query first')
    records = {d['dataset_id']: d for d in source['datasets']}
    ids = args.dataset or source['expected_dataset_ids']
    if not ids or len(set(ids)) != len(ids) or set(ids) - records.keys():
        raise ValueError('unknown/duplicate dataset selection')
    prepared = []
    for id_ in ids:
        if not id_.replace('_', '').isalnum():
            raise ValueError('invalid dataset ID')
        d = records[id_]
        points = frozen(d['input_csv'], d['input_csv_sha256'])
        queries = frozen(d['query_workload']['file'], d['query_workload']['file_sha256'])
        order_paths = {}
        for layout, key in (('hilbert', 'A3_isotropic_hilbert'), ('rch', 'A6_rch')):
            record = d['order_files'][key]
            order_paths[layout] = frozen(record['path'], record['sha256'])
        prepared.append((d, points, queries, order_paths))
    return source, prepared


def measured_dataset(conn, d, point_path, query_path, order_paths, args, out, state):
    dataset_id = d['dataset_id']
    points = np.loadtxt(point_path, delimiter=',', ndmin=2)
    count = len(points)
    if points.shape != (d['point_count'], 3) or not np.isfinite(points).all() or count >= 2**63:
        raise ValueError('point shape/finite/ID range mismatch')
    with query_path.open() as stream:
        queries = list(csv.DictReader(stream))
    if len(queries) != state['queries_per_dataset'] or len({q['query_id'] for q in queries}) != len(queries):
        raise ValueError('query count/ID mismatch')
    oracle = {}
    bounds = {}
    for q in queries:
        box = tuple(float(q[f'{side}_{axis}']) for side in ('min', 'max') for axis in 'xyz')
        if not np.isfinite(box).all() or any(box[i] > box[i + 3] for i in range(3)):
            raise ValueError('invalid query bounds')
        ids = np.flatnonzero(np.all((points >= box[:3]) & (points <= box[3:]), axis=1))
        oracle[q['query_id']] = len(ids), id_hash(ids)
        bounds[q['query_id']] = box
    oracle_path = out / f'{dataset_id}.oracle.json'
    oracle_path.write_text(json.dumps(oracle, indent=2) + '\n')
    schema = 'rch_dbms_' + uuid.uuid4().hex
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    layout_records = []
    try:
        for layout in LAYOUTS:
            permutation = np.arange(count) if layout == 'input' else read_order(order_paths[layout], count)
            t = time.perf_counter()
            create_table(conn, schema, layout)
            with conn.cursor().copy(sql.SQL('COPY {} (point_id,x,y,z) FROM STDIN').format(table_name(schema, layout))) as copy:
                for id_ in permutation:
                    xyz = points[id_]
                    copy.write_row((int(id_), float(xyz[0]), float(xyz[1]), float(xyz[2])))
            load_seconds = time.perf_counter() - t
            t = time.perf_counter()
            conn.execute(sql.SQL('CREATE INDEX ON {} USING gist (geom gist_geometry_ops_nd)').format(table_name(schema, layout)))
            index_seconds = time.perf_counter() - t
            t = time.perf_counter()
            conn.execute(sql.SQL('VACUUM (ANALYZE) {}').format(table_name(schema, layout)))
            analyze_seconds = time.perf_counter() - t
            relation = f'{schema}.{layout}'
            sizes = conn.execute('SELECT pg_table_size(%s::regclass), pg_indexes_size(%s::regclass)', (relation, relation)).fetchone()
            index_definition = conn.execute('SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indrelid=%s::regclass', (relation,)).fetchone()[0]
            if 'gist_geometry_ops_nd' not in index_definition:
                raise ValueError('expected ND GiST operator class')
            actual = conn.execute(sql.SQL('SELECT count(*), min(point_id), max(point_id) FROM {}').format(table_name(schema, layout))).fetchone()
            if actual != (count, 0, count - 1):
                raise ValueError('loaded table cardinality/ID mismatch')
            layout_records.append({'layout': layout, 'load_seconds': load_seconds, 'index_seconds': index_seconds,
                                   'vacuum_analyze_seconds': analyze_seconds, 'table_bytes': sizes[0], 'index_bytes': sizes[1],
                                   'index_definition': index_definition,
                                   'preparation_scope': 'create+COPY, GiST build, VACUUM ANALYZE; excludes earlier SFC ordering and oracle'})
        rng = random.Random(args.seed)
        with (out / f'{dataset_id}.metrics.csv').open('w', newline='') as handle:
            columns = ('dataset_id', 'backend', 'block', 'query_id', 'client_wall_seconds', 'result_count', 'result_hash', 'oracle_match')
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for block in range(args.repeats):
                order = list(BACKENDS)
                rng.shuffle(order)
                state['schedule'].append({'dataset_id': dataset_id, 'block': block, 'order': order})
                for backend in order:
                    print(f'[dbms] {dataset_id} block={block+1}/{args.repeats} {backend}', flush=True)
                    configure_scan(conn, backend)
                    statement = query_statement(schema, backend)
                    for warmup in (True, False):
                        sequence = list(bounds)
                        random.Random(args.seed + block + (0 if warmup else 10000)).shuffle(sequence)
                        for query_id in sequence:
                            params = parameters(bounds[query_id], backend)
                            t = time.perf_counter()
                            returned = conn.execute(statement, params).fetchall()
                            ids = [r[0] for r in returned]
                            elapsed = time.perf_counter() - t
                            signature = len(ids), id_hash(ids)
                            if signature != oracle[query_id]:
                                raise ValueError(f'oracle mismatch: {dataset_id}/{backend}/{query_id}')
                            if not warmup:
                                writer.writerow(dict(zip(columns, (dataset_id, backend, block, query_id, elapsed, *signature, 'true'))))
        # Diagnostic execution is deliberately separate from measured client queries.
        with (out / f'{dataset_id}.plans.jsonl').open('w') as plans:
            for backend in BACKENDS:
                configure_scan(conn, backend)
                for query_id, box in bounds.items():
                    document = conn.execute(sql.SQL('EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON) ') + query_statement(schema, backend), parameters(box, backend)).fetchone()[0][0]
                    if document['Plan']['Actual Rows'] != oracle[query_id][0]:
                        raise ValueError('diagnostic plan row-count mismatch')
                    types = [n['Node Type'] for n in nodes(document['Plan'])]
                    if backend.endswith('_seq') and any('Index' in t or 'Bitmap' in t for t in types):
                        raise ValueError('full scan arm unexpectedly used an index')
                    plans.write(json.dumps({'backend': backend, 'query_id': query_id, 'document': document}) + '\n')
        return {'dataset_id': dataset_id, 'point_count': count, 'query_ids': list(bounds),
                'input_sha256': digest(point_path), 'query_sha256': digest(query_path),
                'source_ordering_wall_seconds': d['ordering_wall_seconds'], 'layouts': layout_records}
    finally:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def run(args):
    if args.output_dir.exists():
        raise ValueError('output root already exists; select a new DBMS_OUTPUT_DIR')
    source, inputs = load_inputs(args)
    args.output_dir.mkdir(parents=True)
    output = args.output_dir
    (output / 'source_manifest.json').write_text((args.source_root / 'run_manifest.json').read_text())
    state = {'schema': 'rch.dbms_benchmark.v1', 'source_rch_layout': 'A6_rch (C0 uniform)', 'created_utc': datetime.now(timezone.utc).isoformat(),
             'platform': platform.platform(), 'repeats': args.repeats, 'seed': args.seed,
             'connection_mode': args.mode, 'backends': list(BACKENDS), 'datasets': [], 'schedule': [],
             'queries_per_dataset': source['query_count_per_dataset_layout'],
             'source_manifest_sha256': digest(output / 'source_manifest.json'), 'files_sha256': {},
             'scope': 'PostGIS point tables, same server, inclusive exact XYZ, ID materialization+transport; warm-workload protocol, no physical cold I/O claim',
             'measurement_protocol': {'driver_version': psycopg.__version__, 'libpq_version': psycopg.pq.version(),
                 'warmup_passes_per_backend_block': 1, 'server_reused_across_blocks': True,
                 'query_result': 'all original IDs, ordered by ID; fetch and Python materialization timed',
                 'diagnostics': 'one separate EXPLAIN ANALYZE BUFFERS TIMING OFF execution per backend/query',
                 'preparation': 'one load/index/vacuum per dataset/layout; prior SFC ordering excluded',
                 'server_cpu_and_rss': 'not measured', 'indexed_scan_policy': 'optimizer may choose sequential scan'},
             'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (Path(__file__), ROOT / 'experiments/runners/dbms_backend.py', ROOT / 'analysis/scripts/analyze_dbms_benchmarks.py')}}
    if args.mode == 'managed':
        manager = managed_server(output / 'postgresql.log')
    else:
        # libpq supports PGUSER/PGHOST/PGSERVICE/.pgpass; secrets never enter manifests.
        manager = contextlib.nullcontext(os.environ.get('RCH_DBMS_DSN', 'dbname=rch_bench'))
    with manager as connection:
        with connect(connection) as conn:
            if args.mode == 'managed':
                conn.execute('CREATE EXTENSION postgis')
            state['server'] = server_info(conn)
            for record in inputs:
                state['datasets'].append(measured_dataset(conn, *record, args, output, state))
    if digest(args.source_root / 'run_manifest.json') != state['source_manifest_sha256']:
        raise ValueError('source manifest changed during run')
    for p in sorted(output.iterdir()):
        if p.is_file():
            state['files_sha256'][p.name] = digest(p)
    (output / 'run_manifest.json').write_text(json.dumps(state, indent=2) + '\n')
    analyze(output, output / 'analysis')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, default=ROOT / APPLICATION_OUTPUT_ROOT)
    p.add_argument('--output-dir', type=Path, default=ROOT / 'experiments/outputs/dbms_benchmark/full_benchmark')
    p.add_argument('--mode', choices=('managed', 'external'), default='managed')
    p.add_argument('--dataset', action='append')
    p.add_argument('--repeats', type=int, default=5)
    p.add_argument('--seed', type=int, default=2026)
    args = p.parse_args()
    if not 1 <= args.repeats <= 10000 or args.seed < 0:
        p.error('invalid repeats/seed')
    run(args)


if __name__ == '__main__':
    main()
