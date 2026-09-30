import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import app.database as database


class AnalyticsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(__file__).parent / f".sentinel-analytics-{uuid4().hex}.db"
        database.init_db()

    def tearDown(self):
        test_db_path = database.DB_PATH
        database.DB_PATH = self.original_db_path
        if test_db_path.exists():
            test_db_path.unlink()

    def test_period_query_and_health(self):
        database.register_or_update_job("analytics_job", name="Analytics Job")
        execution_id = database.record_start("analytics_job")
        database.record_success("analytics_job", execution_id=execution_id, duration_seconds=12.5)

        now = datetime.now()
        rows = database.get_executions_between(now - timedelta(minutes=5), now + timedelta(minutes=5))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "SUCCESS")

        health = database.get_database_health()
        self.assertTrue(health["connected"])
        self.assertEqual(health["jobs_count"], 1)
        self.assertEqual(health["executions_count"], 1)
        self.assertIsNotNone(health["last_updated_at"])

    def test_period_query_rejects_rows_outside_interval(self):
        database.register_or_update_job("empty_job", name="Empty Job")
        future = datetime.now() + timedelta(days=1)
        rows = database.get_executions_between(future, future + timedelta(days=1))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
