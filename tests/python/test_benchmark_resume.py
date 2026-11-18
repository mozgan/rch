"""Resume must preserve overnight measurements, old logs, and completed substeps."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import run_benchmark_pipeline as workflow


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'repo'
        self.archive = self.root / 'backups/archive'
        self.archive.mkdir(parents=True)
        self.evidence = self.root / 'experiments/logs/benchmark_pipeline'
        self.evidence.mkdir(parents=True)
        (self.root / 'paper').mkdir(parents=True)
        (self.root / 'paper/manuscript.tex').write_text('unchanged manuscript')
        self.state_file = self.evidence / 'benchmark_run_results.json'
        state = {
            'archive_root': str(self.archive),
            'manuscript_sha256_before': workflow.sha(self.root / 'paper/manuscript.tex'),
            'stages': [{'command': ['make', stage], 'returncode': 0}
                       for stage in workflow.STAGES[:4]] + [
                           {'command': ['make', 'bench-extended'], 'returncode': 2}],
        }
        self.state_file.write_text(json.dumps(state))
        for name in ['synthetic_dataset', 'real_dataset', 'independent_benchmarks', 'a7_cgal_appendix']:
            p = self.root / 'experiments/outputs' / name
            p.mkdir(parents=True)
            (p / 'complete').write_text(name)
        partial = self.root / 'experiments/outputs/clamping_intervention'
        partial.mkdir()
        (partial / 'old_partial').write_text('preserve this')
        self.old_log = self.evidence / 'benchmark_run_bench-extended.log'
        self.old_log.write_text('original failure log')
        self.patch = patch.object(workflow, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def fake_run(self, command, **kwargs):
        stage = command[1]
        self.assertNotIn(stage, workflow.STAGES[:4])
        for name in workflow.STEP_OUTPUTS.get(stage, []):
            p = self.root / 'experiments/outputs' / name
            p.mkdir(parents=True)
            (p / 'new_output').write_text(stage)
        return SimpleNamespace(returncode=0)

    def test_new_plan_uses_repository_backups_without_creating_them(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            workflow.main([])
        archive = Path(json.loads(stream.getvalue())['archive_root'])
        self.assertTrue(archive.is_relative_to(self.root / 'backups'))
        self.assertFalse(archive.exists())

    def test_archive_rejects_external_cleanup_and_symlink_destinations(self):
        external = self.root.parent / 'external'
        external.mkdir()
        link = self.root / 'backups/external-link'
        link.symlink_to(external, target_is_directory=True)
        for path in (external, self.root / 'experiments/outputs/archive',
                     self.root / 'build/archive', link / 'archive'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'backups directory'):
                    workflow.archive_directory(path)

    def test_plan_is_read_only_and_skips_successful_core_stages(self):
        before = self.state_file.read_bytes()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            workflow.main(['--resume'])
        plan = json.loads(stream.getvalue())
        self.assertEqual(plan['skip_completed'], workflow.STAGES[:4])
        self.assertEqual(plan['move_if_present'], [])
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertTrue((self.root / 'experiments/outputs/clamping_intervention/old_partial').exists())

    def test_resume_preserves_core_outputs_and_failure_log(self):
        with patch.object(workflow.subprocess, 'run', side_effect=self.fake_run) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                workflow.main(['--run', '--resume'])
        self.assertEqual([c.args[0][1] for c in run.call_args_list],
                         workflow.COMPLETION_STEPS + ['test-integration'])
        state = json.loads(self.state_file.read_text())
        self.assertEqual(workflow.pending_stages(state), [])
        self.assertTrue(state['manuscript_unchanged'])
        moved = Path(state['retry_archives'][0]['archive'])
        self.assertEqual((moved / 'old_partial').read_text(), 'preserve this')
        self.assertEqual(self.old_log.read_text(), 'original failure log')
        self.assertEqual(state['stages'][4]['returncode'], 2)
        for name in ['synthetic_dataset', 'real_dataset', 'independent_benchmarks', 'a7_cgal_appendix']:
            self.assertEqual((self.root / 'experiments/outputs' / name / 'complete').read_text(), name)

    def test_second_resume_skips_successful_substep_after_later_failure(self):
        def fail_cost(command, **kwargs):
            result = self.fake_run(command, **kwargs)
            return SimpleNamespace(returncode=2) if command[1] == 'bench-cost-stability' else result
        with patch.object(workflow.subprocess, 'run', side_effect=fail_cost):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    workflow.main(['--run', '--resume'])
        self.assertEqual(failure.exception.code, 2)
        with patch.object(workflow.subprocess, 'run', side_effect=self.fake_run) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                workflow.main(['--run', '--resume'])
        self.assertEqual([c.args[0][1] for c in run.call_args_list],
                         workflow.COMPLETION_STEPS[workflow.COMPLETION_STEPS.index('bench-cost-stability'):] + ['test-integration'])
        state = json.loads(self.state_file.read_text())
        self.assertEqual(len([r for r in state['completion_steps']
                              if r['command'][1] == 'bench-clamping-intervention']), 1)

    def test_fresh_run_refuses_to_discard_unfinished_checkpoint(self):
        before = self.state_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unfinished run'):
            workflow.main(['--run'])
        self.assertEqual(before, self.state_file.read_bytes())

    def test_explicit_completion_recheck_keeps_core_results_and_prior_history(self):
        with patch.object(workflow.subprocess, 'run', side_effect=self.fake_run):
            with contextlib.redirect_stdout(io.StringIO()):
                workflow.main(['--run', '--resume'])
        before = self.state_file.read_bytes()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            workflow.main(['--resume', '--recheck-dependent'])
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(json.loads(stream.getvalue())['skip_completed'], workflow.STAGES[:4])
        with patch.object(workflow.subprocess, 'run', side_effect=self.fake_run) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                workflow.main(['--run', '--resume', '--recheck-dependent'])
        self.assertEqual([c.args[0][1] for c in run.call_args_list],
                         workflow.COMPLETION_STEPS + ['test-integration'])
        state = json.loads(self.state_file.read_text())
        self.assertEqual(workflow.pending_stages(state), [])
        self.assertTrue(any(row.get('status') == 'recheck_requested' for row in state['stages']))
        for name in ['synthetic_dataset', 'real_dataset', 'independent_benchmarks', 'a7_cgal_appendix']:
            self.assertEqual((self.root / 'experiments/outputs' / name / 'complete').read_text(), name)


if __name__ == '__main__':
    unittest.main()
