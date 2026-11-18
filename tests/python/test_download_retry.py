"""Network-free downloader retry/failure tests; waits are mocked."""
import io
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch
from scripts.download_dataset import download_url


class DownloadRetryTest(unittest.TestCase):
    def test_rate_limit_waits_then_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'data.bin'
            failure = HTTPError('https://example.invalid', 429, 'limited', {'Retry-After': '17'}, None)
            with patch('scripts.download_dataset.urllib.request.urlopen', side_effect=[failure, io.BytesIO(b'verified later')]) as open_, patch('scripts.download_dataset.time.sleep') as sleep:
                download_url('https://example.invalid', target)
            sleep.assert_called_once_with(17.)
            self.assertEqual(open_.call_count, 2)
            self.assertEqual(target.read_bytes(), b'verified later')
            self.assertFalse(target.with_suffix('.bin.tmp').exists())

    def test_permanent_error_does_not_retry_or_destroy_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'data.bin'; target.write_bytes(b'existing')
            with patch('scripts.download_dataset.urllib.request.urlopen', side_effect=HTTPError('https://example.invalid', 404, 'missing', {}, None)) as open_, patch('scripts.download_dataset.time.sleep') as sleep:
                with self.assertRaises(HTTPError): download_url('https://example.invalid', target)
            self.assertEqual(open_.call_count, 1); sleep.assert_not_called()
            self.assertEqual(target.read_bytes(), b'existing')

    def test_retries_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'data.bin'
            with patch('scripts.download_dataset.urllib.request.urlopen', side_effect=TimeoutError('timeout')) as open_, patch('scripts.download_dataset.time.sleep') as sleep:
                with self.assertRaises(TimeoutError): download_url('https://example.invalid', target)
            self.assertEqual(open_.call_count, 6); self.assertEqual(sleep.call_count, 5)
            self.assertFalse(target.exists()); self.assertFalse(target.with_suffix('.bin.tmp').exists())

    def test_long_retry_after_fails_without_retrying_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('scripts.download_dataset.urllib.request.urlopen', side_effect=HTTPError('https://example.invalid', 429, 'limited', {'Retry-After': '3600'}, None)), patch('scripts.download_dataset.time.sleep') as sleep:
                with self.assertRaises(RuntimeError): download_url('https://example.invalid', Path(tmp) / 'data')
            sleep.assert_not_called()
