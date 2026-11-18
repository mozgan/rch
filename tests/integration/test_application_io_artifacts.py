#!/usr/bin/env python3
"""Fast frozen-result I/O publication checks; no queries or binaries executed."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    'cache_artifacts', ROOT / 'analysis/scripts/make_application_cache_artifacts.py'
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FrozenIOPublication(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.source = self.root / 'cache'
        self.source.mkdir()
        self.generated = self.root / 'generated'
        self.original_root = module.ROOT
        # Frozen workload paths resolve inside this isolated fixture.
        module.ROOT = self.root
        self.layouts = ['A3_isotropic_hilbert', 'A6_rch_C3']
        queries = [dict(query_id=f'q{i}', min_x='0', min_y='0', min_z='0',
                        max_x='1', max_y='1', max_z='1') for i in range(2)]
        results = [dict(layout_id=layout, query_id=q['query_id'], result_count='1',
                        result_ids_sha256='a' * 64, oracle_match='true')
                   for layout in self.layouts for q in queries]
        write_csv(self.root / 'queries.csv', queries)
        write_csv(self.root / 'results.csv', results)
        records = {name: {'path': path, 'sha256': module.digest(self.root / path)}
                   for name, path in [('query_windows.csv', 'queries.csv'),
                                      ('query_results.csv', 'results.csv')]}
        application = {'query_count_per_dataset_layout': 2, 'datasets': [
            {'dataset_id': 'fixture', 'layout_schedule': self.layouts,
             'query_results': records}]}
        snapshot = self.source / 'application_source_manifest.json'
        snapshot.write_text(json.dumps(application))
        self.manifest = {'status': 'completed', 'identity': {
            'application_manifest_sha256': module.digest(snapshot),
            'datasets': ['fixture'], 'repeats': 2,
            'modes': ['cold_page_cache', 'warm_page_cache']}, 'tasks': {}}
        summary = []
        for layout in self.layouts:
            key = 'fixture__' + layout
            text = ''.join('\t'.join(list(q.values()) + ['1', 'a' * 64]) + '\n'
                           for q in queries)
            (self.source / (key + '.oracle.tsv')).write_text(text)
            raw = [dict(query_id=q['query_id'], repeat=str(repeat), cache_mode=mode,
                        resident_pages_before='0' if mode=='cold_page_cache' else '8',
                        total_os_pages='8', wall_seconds='0.0001', logical_bytes='4096',
                        os_read_bytes='8192' if mode=='cold_page_cache' else '0',
                        result_count='1', result_sha256='a' * 64, oracle_match='true')
                   for q in queries for repeat in (1, 2)
                   for mode in self.manifest['identity']['modes']]
            path = self.source / (key + '.csv')
            write_csv(path, raw)
            self.manifest['tasks'][key] = {
                'status': 'passed', 'metrics': path.name,
                'metrics_sha256': module.digest(path),
                'oracle_sha256': records['query_results.csv']['sha256'],
                'query_sha256': records['query_windows.csv']['sha256']}
            for mode in self.manifest['identity']['modes']:
                summary.append(dict(dataset_id='fixture', layout_id=layout, cache_mode=mode,
                                    measured_rows='4', mean_logical_bytes='4096',
                                    mean_os_read_bytes='8192' if mode=='cold_page_cache' else '0',
                                    os_read_bytes_available_rows='4'))
        write_csv(self.source / 'summary.csv', summary)
        self.manifest['summary_sha256'] = module.digest(self.source / 'summary.csv')
        self.save_manifest()

    def tearDown(self):
        module.ROOT = self.original_root
        self.work.cleanup()

    def save_manifest(self):
        (self.source / 'run_manifest.json').write_text(json.dumps(self.manifest))

    def publish(self):
        return module.publish_storage_io(self.source, self.generated)

    def test_valid_data_and_proof(self):
        table = self.publish()
        self.assertIn('4.00 & 8.00 & 0.00', table.read_text())
        proof = json.loads((self.generated / 'outputs/application_cache/io_analysis_manifest.json').read_text())
        for name, checksum in proof['artifacts_sha256'].items():
            self.assertEqual(module.digest(self.generated / name), checksum)

    def test_corrupt_metrics_rejected(self):
        item = next(iter(self.manifest['tasks'].values()))
        (self.source / item['metrics']).write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.publish()

    def test_false_summary_with_updated_hash_rejected(self):
        path = self.source / 'summary.csv'
        with path.open() as stream:
            rows = list(csv.DictReader(stream))
        rows[0]['mean_os_read_bytes'] = '1024'
        write_csv(path, rows)
        self.manifest['summary_sha256'] = module.digest(path)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'mean differs'):
            self.publish()

    def test_cached_oracle_must_match_frozen_source(self):
        path = self.source / ('fixture__' + self.layouts[0] + '.oracle.tsv')
        path.write_text(path.read_text().replace('a' * 64, 'b' * 64))
        with self.assertRaisesRegex(ValueError, 'oracle TSV differs'):
            self.publish()

    def test_missing_counter_is_not_zero(self):
        with (self.source / 'summary.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        rows[0]['mean_os_read_bytes'] = ''
        rows[0]['os_read_bytes_available_rows'] = '0'
        self.assertIn('--', module.storage_read_table(rows, ['fixture'], self.layouts))


if __name__ == '__main__':
    unittest.main()
