import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import runner
from config import Config
from runner import Runner, fibonacci_delays
from store import Store, init_db


def make_config(db_path: Path) -> Config:
    return Config(
        Namespace(
            db=str(db_path),
            host="127.0.0.1",
            port=8080,
            timezone="America/Lima",
            run_at="07:00",
            retry_seconds=0,
            start_before_minutes=0,
            stop_after_minutes=1,
            admin_token="test",
            telegram_bot_token="",
            telegram_admin_ids="",
        )
    )


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        init_db(self.db_path)
        self.store = Store(self.db_path)
        self.config = make_config(self.db_path)
        self.original_post_registro = runner.post_registro

    def tearDown(self) -> None:
        runner.post_registro = self.original_post_registro
        self.tempdir.cleanup()

    def test_skips_student_with_existing_ticket(self) -> None:
        student = self.store.add_student("11111111", "2023000001G", "Uno")
        self.store.record_attempt(
            student_id=student["id"],
            run_date=runner.datetime.now(self.config.timezone).date().isoformat(),
            status="ok",
            http_status=200,
            ticket_codigo="TK1",
            response_json={"code": 200, "t2_codigo": "TK1"},
        )
        calls = []

        def fake_post_registro(dni: str, codigo: str) -> tuple[int, dict]:
            calls.append((dni, codigo))
            return 200, {"code": 200, "t2_codigo": "TK2"}

        runner.post_registro = fake_post_registro

        result = Runner(self.config, self.store).run_once_for_all()

        self.assertEqual(result["results"][0]["status"], "skipped_ticket_exists")
        self.assertEqual(calls, [])

    def test_stops_batch_when_no_quota_response_is_seen(self) -> None:
        self.store.add_student("11111111", "2023000001G", "Uno")
        self.store.add_student("22222222", "2023000002G", "Dos")
        calls = []

        def fake_post_registro(dni: str, codigo: str) -> tuple[int, dict]:
            calls.append((dni, codigo))
            return 200, {"code": 400, "t3_cupos": 0, "message": "SIN CUPOS DISPONIBLES"}

        runner.post_registro = fake_post_registro

        result = Runner(self.config, self.store).run_once_for_all()

        self.assertEqual(result["status"], "quota_exhausted")
        self.assertTrue(result["quota_exhausted"])
        # In parallel mode, both calls are launched
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["results"][0]["status"], "no_quota")

    def test_treats_code_500_without_ticket_as_no_quota(self) -> None:
        self.store.add_student("11111111", "2023000001G", "Uno")
        self.store.add_student("22222222", "2023000002G", "Dos")
        calls = []

        def fake_post_registro(dni: str, codigo: str) -> tuple[int, dict]:
            calls.append((dni, codigo))
            return 200, {"code": 500}

        runner.post_registro = fake_post_registro

        result = Runner(self.config, self.store).run_once_for_all()

        self.assertEqual(result["status"], "quota_exhausted")
        self.assertTrue(result["quota_exhausted"])
        # In parallel mode, both calls are launched
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["results"][0]["status"], "no_quota")

    def test_fibonacci_retry_delays(self) -> None:
        delays = fibonacci_delays()

        self.assertEqual([next(delays) for _ in range(8)], [1, 1, 2, 3, 5, 8, 13, 21])


if __name__ == "__main__":
    unittest.main()
