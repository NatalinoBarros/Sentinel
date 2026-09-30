import unittest

from app.telegram_bot import (
    build_executions_message,
    build_status_messages,
    parse_command,
    parse_weekday_spec,
)


class TelegramBotTests(unittest.TestCase):
    def test_parse_command_with_bot_suffix(self):
        self.assertEqual(parse_command("/ultimas@sentinel_bot meu_job 10"), ("ultimas", ["meu_job", "10"]))

    def test_status_lists_every_job(self):
        jobs = [
            {"job_id": "job_ok", "name": "Job OK", "last_status": "SUCCESS"},
            {"job_id": "job_fail", "name": "Job Falha", "last_status": "FAILED"},
        ]
        message = "\n".join(build_status_messages(jobs))
        self.assertIn("job_ok", message)
        self.assertIn("job_fail", message)
        self.assertIn("Saudável", message)
        self.assertIn("Com falha", message)

    def test_execution_history_escapes_error(self):
        job = {"job_id": "job_1", "name": "Teste"}
        executions = [{
            "status": "FAILED",
            "started_at": "2026-09-15T09:00:00",
            "duration_seconds": 4.2,
            "error_message": "valor < inválido",
        }]
        message = build_executions_message(job, executions)
        self.assertIn("15/09/2026 09:00", message)
        self.assertIn("valor &lt; inválido", message)

    def test_parse_weekday_ranges(self):
        self.assertEqual(parse_weekday_spec("1-5"), [1, 2, 3, 4, 5])
        self.assertEqual(parse_weekday_spec("1,3,7"), [1, 3, 7])
        self.assertEqual(parse_weekday_spec("diasuteis"), [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
