"""Reject false certainty from missing telemetry and verify checksum guards."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis.scripts import analyze_fallback_evidence as audit


class FallbackEvidenceTest(unittest.TestCase):
    def metadata(self, flag, mode, estimator='det_mcd'):
        return {'method': 'rch', 'frame_estimator': estimator,
                'robust_fallback_used': flag,
                'fitted_frame_diagnostics': {'mode': mode} if mode is not None else None}

    def test_mechanisms_are_counted_independently(self):
        combinations = [(True, 'principal_eigenframe'), (False, 'canonical_axes_fallback'),
                        (True, 'canonical_axes_fallback'), (False, 'principal_eigenframe')]
        records = [{'family': 'fixture', **audit.classify(self.metadata(flag, mode))}
                   for flag, mode in combinations]
        summary = audit.summarize(records)[0]
        self.assertEqual(summary['estimator_fallback_records'], 2)
        self.assertEqual(summary['canonical_axes_records'], 2)
        self.assertEqual(summary['both_fallbacks_records'], 1)
        self.assertEqual(summary['estimator_flag_known'], 4)

    def test_missing_fields_remain_unknown(self):
        row = audit.classify({'method': 'rch', 'frame_estimator': 'det_mcd'})
        self.assertIsNone(row['estimator_fallback'])
        self.assertEqual(row['frame_mode'], 'unknown')
        summary = audit.summarize([{'family': 'fixture', **row}])[0]
        self.assertEqual(summary['estimator_flag_unknown'], 1)
        self.assertEqual(summary['frame_mode_unknown'], 1)
        self.assertEqual(summary['estimator_flag_known'], 0)

    def test_requested_sample_frame_is_not_an_estimator_failure_trial(self):
        row = audit.classify(self.metadata(False, 'canonical_axes_fallback', 'sample_covariance'))
        summary = audit.summarize([{'family': 'fixture', **row}])[0]
        self.assertEqual(summary['robust_attempt_records'], 0)
        self.assertEqual(summary['canonical_axes_records'], 1)

    def test_unknown_estimator_does_not_become_explicit_sample_control(self):
        row = audit.classify({'method': 'rch'})
        self.assertIsNone(row['robust_attempt'])
        summary = audit.summarize([{'family': 'fixture', **row}])[0]
        self.assertEqual(summary['estimator_applicability_unknown'], 1)

    def test_unknown_method_or_mode_and_string_flags_rejected(self):
        for value in [self.metadata('false', 'principal_eigenframe'),
                      self.metadata(False, 'unrecognized_mode'), {'method': 'unrecognized_method'}]:
            with self.assertRaises(ValueError):
                audit.classify(value)

    def test_raw_hilbert_is_not_a_frame_trial(self):
        row = audit.classify({'method': 'isotropic_hilbert', 'frame_estimator': 'none'})
        self.assertFalse(row['frame_applicable'])
        self.assertEqual(row['frame_mode'], 'not_applicable')

    def test_changed_source_or_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'output'
            output.mkdir()
            source = root / 'input.json'
            source.write_text('{}')
            artifact = output / 'summary.csv'
            artifact.write_text('count\n1\n')
            state = {'analyzer_sha256': audit.digest(Path(audit.__file__)),
                     'sources_sha256': {'input.json': audit.digest(source)},
                     'artifacts': {'summary.csv': audit.digest(artifact)},
                     'manifest_records': 1, 'frame_records': 1}
            (output / 'analysis_manifest.json').write_text(json.dumps(state))
            with patch.object(audit, 'ROOT', root):
                self.assertEqual(audit.validate(output, root)['status'], 'passed')
                source.write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    audit.validate(output, root)
                source.write_text('{}')
                artifact.write_text('count\n2\n')
                with self.assertRaisesRegex(ValueError, 'artifact changed'):
                    audit.validate(output, root)


if __name__ == '__main__':
    unittest.main()
