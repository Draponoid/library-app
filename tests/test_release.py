import importlib.util
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location('release_smoke', Path(__file__).resolve().parents[1] / 'scripts' / 'smoke-release.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ReleaseSettingsTests(unittest.TestCase):
    def test_rejects_missing_smoke_password(self):
        with tempfile.TemporaryDirectory() as temp:
            env = Path(temp) / '.env'
            env.write_text('DATABASE_URL=postgresql://example\nSECRET_KEY=abc\nCD_SMOKE_USERNAME=librarian\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'CD_SMOKE_PASSWORD'):
                smoke.settings(env)

    def test_reads_port_and_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            env = Path(temp) / '.env'
            env.write_text('DATABASE_URL=postgresql://example\nSECRET_KEY=abc\nCD_SMOKE_USERNAME=librarian\nCD_SMOKE_PASSWORD=test-password\nHTTP_PORT=18081\n', encoding='utf-8')
            values, port = smoke.settings(env)
            self.assertEqual(port, 18081)
            self.assertEqual(values['CD_SMOKE_USERNAME'], 'librarian')

    def test_rejects_out_of_range_port(self):
        with tempfile.TemporaryDirectory() as temp:
            env = Path(temp) / '.env'
            env.write_text('DATABASE_URL=postgresql://example\nSECRET_KEY=abc\nCD_SMOKE_USERNAME=reader\nCD_SMOKE_PASSWORD=test-password\nHTTP_PORT=70000\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'HTTP_PORT'):
                smoke.settings(env)
