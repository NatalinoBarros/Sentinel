import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import app.database as database
from client.monitor import SentinelMonitor


class LanguageMetadataTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(__file__).parent / f".sentinel-language-{uuid4().hex}.db"
        database.init_db()

    def tearDown(self):
        test_db_path = database.DB_PATH
        database.DB_PATH = self.original_db_path
        if test_db_path.exists():
            test_db_path.unlink()

    def test_language_is_saved_and_preserved_on_manual_update(self):
        database.register_or_update_job("job_php", name="Job PHP", language="php")
        self.assertEqual(database.get_job("job_php")["language"], "php")

        database.register_or_update_job("job_php", name="Job PHP editado")
        self.assertEqual(database.get_job("job_php")["language"], "php")

    def test_start_ping_updates_existing_job_language(self):
        database.register_or_update_job("job_python", name="Job Python")
        self.assertIsNone(database.get_job("job_python")["language"])

        database.record_start("job_python", language="python")
        self.assertEqual(database.get_job("job_python")["language"], "python")

    def test_python_client_identifies_its_language(self):
        with patch("client.monitor._http_post") as http_post:
            http_post.side_effect = [
                {"execution_id": 10},
                {"status": "ok"},
            ]
            with SentinelMonitor("job_python", "Job Python"):
                pass

        start_payload = http_post.call_args_list[0].args[1]
        self.assertEqual(start_payload["language"], "python")


if __name__ == "__main__":
    unittest.main()
