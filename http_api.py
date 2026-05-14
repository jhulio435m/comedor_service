import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

from config import Config
from runner import Runner
from store import Store


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalido: {exc}") from exc


def make_handler(config: Config, store: Store, runner: Runner) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self.write_json({"ok": True})
                return
            if not self.authorized():
                self.write_json({"error": "no autorizado"}, HTTPStatus.UNAUTHORIZED)
                return
            if self.path == "/students":
                self.write_json({"students": store.list_students()})
                return
            if self.path.startswith("/attempts"):
                self.write_json({"attempts": store.recent_attempts()})
                return
            self.write_json({"error": "ruta no encontrada"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self.authorized():
                self.write_json({"error": "no autorizado"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                if self.path == "/students":
                    body = parse_json_body(self)
                    student = store.add_student(
                        dni=str(body.get("dni", "")),
                        codigo=str(body.get("codigo", "")),
                        nombre=str(body.get("nombre", "")),
                    )
                    self.write_json({"student": student}, HTTPStatus.CREATED)
                    return
                if self.path.startswith("/students/") and self.path.endswith("/disable"):
                    student_id = int(self.path.split("/")[2])
                    student = store.set_student_active(student_id, False)
                    self.write_json({"student": student} if student else {"error": "no encontrado"})
                    return
                if self.path.startswith("/students/") and self.path.endswith("/enable"):
                    student_id = int(self.path.split("/")[2])
                    student = store.set_student_active(student_id, True)
                    self.write_json({"student": student} if student else {"error": "no encontrado"})
                    return
                if self.path == "/run":
                    threading.Thread(target=runner.run_until_ready, daemon=True).start()
                    self.write_json({"status": "started"})
                    return
            except ValueError as exc:
                self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.write_json({"error": "ruta no encontrada"}, HTTPStatus.NOT_FOUND)

        def do_PATCH(self) -> None:
            if not self.authorized():
                self.write_json({"error": "no autorizado"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                if self.path.startswith("/students/"):
                    student_id = int(self.path.split("/")[2])
                    body = parse_json_body(self)
                    student = store.update_student(
                        student_id,
                        dni=str(body["dni"]) if "dni" in body else None,
                        codigo=str(body["codigo"]) if "codigo" in body else None,
                        nombre=str(body["nombre"]) if "nombre" in body else None,
                    )
                    self.write_json({"student": student} if student else {"error": "no encontrado"})
                    return
            except ValueError as exc:
                self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.write_json({"error": "ruta no encontrada"}, HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:
            if not self.authorized():
                self.write_json({"error": "no autorizado"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                if self.path.startswith("/students/"):
                    student_id = int(self.path.split("/")[2])
                    deleted = store.delete_student(student_id)
                    self.write_json({"deleted": deleted} if deleted else {"error": "no encontrado"})
                    return
            except ValueError as exc:
                self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.write_json({"error": "ruta no encontrada"}, HTTPStatus.NOT_FOUND)

        def authorized(self) -> bool:
            if not config.admin_token:
                return True
            return self.headers.get("Authorization") == f"Bearer {config.admin_token}"

        def write_json(self, data: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.log_date_time_string()} {fmt % args}")

    return Handler
