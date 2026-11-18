#!/usr/bin/env python3
"""Small live PostgreSQL/PostGIS correctness and artifact smoke; no system cluster changes."""
import csv
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.application_layouts import LAYOUTS, RULES
sys.path.insert(0, str(ROOT / 'analysis/scripts'))
from analyze_dbms_benchmarks import BACKENDS, digest, validate


def main():
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rch_dbms_smoke_', dir=ROOT / 'build') as directory:
        root = Path(directory)
        points = [(float(i % 16), float((i // 16) % 16), float(i // 256)) for i in range(4096)]
        points += [(0., 0., 0.), (0., 0., 1.), (1e9, -1e9, 3.), (1e9 + .00001, -1e9, 3.)]
        xyz = root / 'points.csv'
        xyz.write_text(''.join(','.join(map(str, p)) + '\n' for p in points))
        boxes = {'all': ((-2e9, -2e9, -2e9), (2e9, 2e9, 2e9)),
                 'point': ((0., 0., 0.), (0., 0., 0.)),
                 'z_only': ((0., 0., 1.), (0., 0., 1.)),
                 'empty': ((100., 100., 100.), (101., 101., 101.)),
                 'slab': ((0., 0., 0.), (15., 15., 0.)),
                 'boundary': ((0., 0., 0.), (8., 8., 8.)),
                 'precision': ((1e9, -1e9, 3.), (1e9, -1e9, 3.)),
                 'precision_next': ((1e9 + .00001, -1e9, 3.), (1e9 + .00001, -1e9, 3.))}
        queries = root / 'queries.csv'
        queries.write_text('query_id,min_x,min_y,min_z,max_x,max_y,max_z\n' + ''.join(
            q + ',' + ','.join(map(str, (*a, *b))) + '\n' for q, (a, b) in boxes.items()))
        order_paths = {}
        for layout, ids in [('hilbert', reversed(range(len(points)))), ('rch', list(range(0, len(points), 2)) + list(range(1, len(points), 2)))]:
            path = root / (layout + '.order.csv')
            path.write_text('rank,raw_index,key\n' + ''.join(f'{rank},{id_},0\n' for rank, id_ in enumerate(ids)))
            order_paths[layout] = {'path': str(path.relative_to(ROOT)), 'sha256': digest(path)}
        source = root / 'source'
        source.mkdir()
        manifest = {'schema': 'rch.application_query', 'protocol': 'application_window_query',
                    'ordering': {'layouts': list(LAYOUTS), 'layout_rules': RULES},
                    'expected_dataset_ids': ['fixture'], 'query_count_per_dataset_layout': len(boxes),
                    'datasets': [{'dataset_id': 'fixture', 'point_count': len(points),
                        'input_csv': str(xyz.relative_to(ROOT)), 'input_csv_sha256': digest(xyz),
                        'query_workload': {'file': str(queries.relative_to(ROOT)), 'file_sha256': digest(queries)},
                        'order_files': {'A3_isotropic_hilbert': order_paths['hilbert'], 'A6_rch': order_paths['rch']},
                        'ordering_wall_seconds': {'A3_isotropic_hilbert': 0, 'A6_rch': 0}}]}
        (source / 'run_manifest.json').write_text(json.dumps(manifest))
        output = root / 'output'
        command = [sys.executable, str(ROOT / 'experiments/runners/run_dbms_benchmarks.py'),
                   '--source-root', str(source), '--output-dir', str(output), '--repeats', '2']
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        state, _, plans = validate(output)
        rows = list(csv.DictReader((output / 'fixture.metrics.csv').open()))
        assert len(rows) == len(BACKENDS) * 2 * len(boxes)
        for r in rows:
            a, b = boxes[r['query_id']]
            ids = [i for i, p in enumerate(points) if all(a[k] <= p[k] <= b[k] for k in range(3))]
            sha = hashlib.sha256(b''.join(struct.pack('<Q', id_) for id_ in ids)).hexdigest()
            assert (int(r['result_count']), r['result_hash']) == (len(ids), sha)
        assert any(p['index_used'] for p in plans), 'GiST was never exercised'
        assert all(not p['index_used'] for p in plans if p['backend'].endswith('_seq'))
        assert 'database system is shut down' in (output / 'postgresql.log').read_text()
        assert subprocess.run(command, capture_output=True).returncode != 0
        artifacts = root / 'artifacts'
        analyzer = [sys.executable, str(ROOT / 'analysis/scripts/analyze_dbms_benchmarks.py'),
                    '--input-root', str(output), '--output-dir', str(artifacts / 'outputs'),
                    '--artifact-root', str(artifacts), '--application-root', str(source)]
        subprocess.run(analyzer, check=True, capture_output=True)
        subprocess.run(analyzer + ['--validate-only'], check=True, capture_output=True)
        other_source = root / 'other_application'; other_source.mkdir()
        (other_source / 'run_manifest.json').write_text('{}')
        rejected = subprocess.run(analyzer[:-1] + [str(other_source), '--validate-only'], capture_output=True, text=True)
        assert rejected.returncode != 0 and 'application run' in rejected.stderr
        manifest_path = output / 'run_manifest.json'
        original_manifest = manifest_path.read_text()
        changed = json.loads(original_manifest)
        changed['source_sha256']['experiments/runners/run_dbms_benchmarks.py'] = '0' * 64
        manifest_path.write_text(json.dumps(changed))
        try:
            validate(output)
        except ValueError as exc:
            assert 'benchmark source changed' in str(exc)
        else:
            raise AssertionError('changed benchmark source accepted')
        finally:
            manifest_path.write_text(original_manifest)
        assert (artifacts / 'figures/fig_dbms_query_latency.pdf').is_file()
        # External connections use the same adapter without changing system roles.
        sys.path.insert(0, str(ROOT / 'experiments/runners'))
        from dbms_backend import managed_server, connect
        from psycopg.conninfo import make_conninfo
        with managed_server(root / 'external-server.log') as connection:
            with connect(connection) as conn:
                conn.execute('CREATE EXTENSION postgis')
            external_output = root / 'external'
            external_command = [sys.executable, str(ROOT / 'experiments/runners/run_dbms_benchmarks.py'),
                '--source-root', str(source), '--output-dir', str(external_output), '--mode', 'external', '--repeats', '1']
            env = dict(os.environ, RCH_DBMS_DSN=make_conninfo(**connection))
            subprocess.run(external_command, env=env, check=True, capture_output=True)
            validate(external_output)
        assert 'database system is shut down' in (root / 'external-server.log').read_text()
        # Exceptions must stop/remove only the private runtime too.
        try:
            with managed_server(root / 'failed-server.log') as connection:
                socket = Path(connection['host'])
                raise RuntimeError('intentional lifecycle failure')
        except RuntimeError as exc:
            assert str(exc) == 'intentional lifecycle failure'
        assert not socket.parent.exists()
        assert 'database system is shut down' in (root / 'failed-server.log').read_text()
        with (artifacts / 'tables/table_dbms_query.tex').open('a') as handle:
            handle.write('tampered\n')
        assert subprocess.run(analyzer + ['--validate-only'], capture_output=True).returncode != 0
        metric = output / 'fixture.metrics.csv'
        lines = metric.read_text().splitlines(keepends=True)
        metric.write_text(''.join(lines[:-1]))
        state['files_sha256'][metric.name] = digest(metric)
        (output / 'run_manifest.json').write_text(json.dumps(state))
        try:
            validate(output)
        except ValueError:
            pass
        else:
            raise AssertionError('incomplete matrix accepted')
        print(json.dumps({'status': 'passed', 'rows': len(rows), 'backends': len(BACKENDS), 'queries': len(boxes),
                          'index_plans': sum(p['index_used'] for p in plans)}))


if __name__ == '__main__':
    main()
