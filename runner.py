import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator

from comedor_api import post_registro
from config import Config
from store import Store


NO_QUOTA_TEXTS = (
    "cupos agotados",
    "sin cupos",
    "sin cupos disponibles",
    "no hay cupos",
    "cupos habilitados para hoy se ha agotado",
)


def to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def response_contains_no_quota_text(data: dict[str, Any]) -> bool:
    try:
        text = json.dumps(data, ensure_ascii=False).lower()
    except TypeError:
        text = str(data).lower()
    return any(fragment in text for fragment in NO_QUOTA_TEXTS)


def is_no_quota_response(data: dict[str, Any]) -> bool:
    if data.get("t2_codigo"):
        return False

    if to_int(data.get("code")) == 500:
        return True

    cupos = to_int(data.get("t3_cupos"))
    if cupos is not None and cupos <= 0:
        return True

    contador = data.get("contador")
    if isinstance(contador, dict):
        contador_cupos = to_int(contador.get("t3_cupos"))
        if contador_cupos is not None and contador_cupos <= 0:
            return True

    return response_contains_no_quota_text(data)


def fibonacci_delays() -> Iterator[int]:
    current = 1
    next_value = 1
    while True:
        yield current
        current, next_value = next_value, current + next_value


class Runner:
    def __init__(self, config: Config, store: Store) -> None:
        self.config = config
        self.store = store
        self.run_lock = threading.Lock()
        self.window_lock = threading.Lock()
        self.last_run_date: str | None = None
        self.completion_callbacks: list[Callable[[dict[str, Any]], None]] = []

    def add_completion_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self.completion_callbacks.append(callback)

    def run_once_for_all(self) -> dict[str, Any]:
        if not self.run_lock.acquire(blocking=False):
            return {"status": "busy", "message": "ya hay una ejecucion en curso"}
        try:
            today = datetime.now(self.config.timezone).date().isoformat()
            results = []
            students_to_run = []

            for student in self.store.active_students():
                existing_ticket = self.store.ticket_for_today(student["id"], today)
                if existing_ticket:
                    results.append(
                        {
                            "student_id": student["id"],
                            "dni": student["dni"],
                            "codigo": student["codigo"],
                            "status": "skipped_ticket_exists",
                            "ticket_codigo": existing_ticket,
                        }
                    )
                    continue
                students_to_run.append(student)

            quota_exhausted = False
            if students_to_run:
                with ThreadPoolExecutor(max_workers=min(len(students_to_run), 20)) as executor:
                    future_to_student = {
                        executor.submit(self.run_student, s, today): s for s in students_to_run
                    }
                    for future in as_completed(future_to_student):
                        result = future.result()
                        results.append(result)
                        if result.get("quota_exhausted"):
                            quota_exhausted = True

            # Sort results by student_id for consistency
            results.sort(key=lambda x: x["student_id"])

            return {
                "status": "quota_exhausted" if quota_exhausted else "done",
                "run_date": today,
                "results": results,
                "quota_exhausted": quota_exhausted,
            }
        finally:
            self.run_lock.release()

    def run_student(self, student: dict[str, Any], run_date: str) -> dict[str, Any]:
        try:
            http_status, data = post_registro(student["dni"], student["codigo"])
            code = data.get("code")
            ticket = data.get("t2_codigo")
            ok = http_status in (200, 201) and code in (200, 201) and bool(ticket)
            if ok:
                status = "ok"
            elif is_no_quota_response(data):
                status = "no_quota"
            else:
                status = "inactive_or_unexpected"
            self.store.record_attempt(
                student_id=student["id"],
                run_date=run_date,
                status=status,
                http_status=http_status,
                ticket_codigo=ticket,
                response_json=data,
            )
            return {
                "student_id": student["id"],
                "dni": student["dni"],
                "codigo": student["codigo"],
                "status": status,
                "ticket_codigo": ticket,
                "code": code,
                "quota_exhausted": status == "no_quota",
            }
        except Exception as exc:
            self.store.record_attempt(
                student_id=student["id"],
                run_date=run_date,
                status="error",
                error=str(exc),
            )
            return {
                "student_id": student["id"],
                "dni": student["dni"],
                "codigo": student["codigo"],
                "status": "error",
                "error": str(exc),
            }

    def run_until_ready(self) -> dict[str, Any]:
        if not self.window_lock.acquire(blocking=False):
            result = {"status": "busy", "message": "ya hay una ejecucion en curso"}
            self.notify_completion(result)
            return result
        try:
            deadline = self.current_deadline()
            last_result: dict[str, Any] = {"status": "not_started"}
            delays = fibonacci_delays()
            while datetime.now(self.config.timezone) <= deadline:
                last_result = self.run_once_for_all()
                if last_result.get("quota_exhausted"):
                    self.notify_completion(last_result)
                    return last_result
                if self.all_active_students_ok(last_result):
                    self.notify_completion(last_result)
                    return last_result
                remaining_seconds = (deadline - datetime.now(self.config.timezone)).total_seconds()
                if remaining_seconds <= 0:
                    break
                time.sleep(min(next(delays), remaining_seconds))
            result = {"status": "deadline_reached", "last_result": last_result}
            self.notify_completion(result)
            return result
        finally:
            self.window_lock.release()

    def notify_completion(self, result: dict[str, Any]) -> None:
        for callback in self.completion_callbacks:
            try:
                callback(result)
            except Exception as exc:
                print(f"Completion callback error: {exc}")

    def target_time_today(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(self.config.timezone)
        hour, minute = [int(part) for part in self.config.run_at.split(":", 1)]
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def current_deadline(self) -> datetime:
        now = datetime.now(self.config.timezone)
        target = self.target_time_today(now)
        deadline = target + timedelta(minutes=self.config.stop_after_minutes)
        if now > deadline:
            return now
        return deadline

    def all_active_students_ok(self, result: dict[str, Any]) -> bool:
        results = result.get("results")
        if not results:
            return False
        return all(item.get("status") in ("ok", "skipped_ticket_exists") for item in results)

    def scheduler_loop(self) -> None:
        while True:
            now = datetime.now(self.config.timezone)
            target = self.target_time_today(now)
            start_at = target - timedelta(minutes=self.config.start_before_minutes)
            stop_at = target + timedelta(minutes=self.config.stop_after_minutes)
            if start_at <= now <= stop_at and self.last_run_date != now.date().isoformat():
                self.last_run_date = now.date().isoformat()
                threading.Thread(target=self.run_until_ready, daemon=True).start()
            time.sleep(10)
