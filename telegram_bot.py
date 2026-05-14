import threading
import time
from datetime import datetime
from typing import Any

import requests

from config import Config
from html_utils import h, pre
from runner import Runner
from store import Store


def status_label(active: int) -> str:
    return "ACTIVO" if active else "INACTIVO"


def hide_token(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "<telegram-token>")


class TelegramBot:
    def __init__(self, config: Config, store: Store, runner: Runner) -> None:
        self.config = config
        self.store = store
        self.runner = runner
        self.base_url = f"https://api.telegram.org/bot{config.telegram_bot_token}"
        self.offset = 0
        self.pending_actions: dict[int, str] = {}

    def polling_loop(self) -> None:
        print("Telegram bot activo con long polling")
        while True:
            try:
                updates = self.telegram_request(
                    "getUpdates",
                    {
                        "offset": self.offset,
                        "timeout": 30,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=35,
                ).get("result", [])
                for update in updates:
                    self.offset = max(self.offset, update["update_id"] + 1)
                    self.handle_update(update)
            except Exception as exc:
                print(f"Telegram polling error: {hide_token(str(exc), self.config.telegram_bot_token)}")
                time.sleep(5)

    def telegram_request(
        self,
        method: str,
        payload: dict[str, Any],
        timeout: int = 15,
    ) -> dict[str, Any]:
        response = requests.post(f"{self.base_url}/{method}", json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        return data

    def handle_update(self, update: dict[str, Any]) -> None:
        callback_query = update.get("callback_query")
        if callback_query:
            self.handle_callback(callback_query)
            return

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or user_id is None or not text:
            return

        if not self.authorized(user_id):
            self.send_message(
                chat_id,
                "<b>No autorizado</b>\n"
                "Envia este ID al administrador para habilitarte:\n"
                f"<code>{user_id}</code>",
            )
            return

        try:
            if chat_id in self.pending_actions and not text.startswith("/"):
                reply = self.handle_pending_action(chat_id, text)
                self.send_reply(chat_id, reply)
                return
            reply = self.handle_command(text)
        except Exception as exc:
            reply = f"<b>Error</b>\n<code>{h(exc)}</code>"
        self.send_reply(chat_id, reply)

    def authorized(self, user_id: int) -> bool:
        return bool(self.config.telegram_admin_ids) and user_id in self.config.telegram_admin_ids

    def send_reply(self, chat_id: int, reply: str | dict[str, Any]) -> None:
        if isinstance(reply, dict):
            self.send_message(chat_id, reply["text"], reply.get("reply_markup"))
            return
        self.send_message(chat_id, reply)

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:3900],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self.telegram_request("sendMessage", payload)

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:3900],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self.telegram_request("editMessageText", payload)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self.telegram_request(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text[:200]},
        )

    def handle_callback(self, callback_query: dict[str, Any]) -> None:
        user = callback_query.get("from") or {}
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        user_id = user.get("id")
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        callback_id = callback_query.get("id")
        data = callback_query.get("data") or ""
        if callback_id is None or chat_id is None or message_id is None or user_id is None:
            return
        if not self.authorized(user_id):
            self.answer_callback(callback_id, "No autorizado")
            return

        try:
            if data == "students":
                self.pending_actions.pop(chat_id, None)
                self.answer_callback(callback_id, "Lista actualizada")
                self.edit_message(chat_id, message_id, self.format_students(), self.students_keyboard())
                return
            if data == "tickets":
                self.pending_actions.pop(chat_id, None)
                self.answer_callback(callback_id, "Tickets actualizados")
                self.edit_message(chat_id, message_id, self.format_tickets(), self.tickets_keyboard())
                return
            if data == "run":
                threading.Thread(target=self.runner.run_until_ready, daemon=True).start()
                self.answer_callback(callback_id, "Ejecucion iniciada")
                self.edit_message(chat_id, message_id, self.run_started_text(), self.tickets_keyboard())
                return
            if data.startswith("action:"):
                self.request_student_id(chat_id, message_id, callback_id, data.split(":", 1)[1])
                return
            if data.startswith("toggle:"):
                self.toggle_student(chat_id, message_id, callback_id, int(data.split(":", 1)[1]))
                return
            if data.startswith("edit:"):
                self.send_edit_template(chat_id, callback_id, int(data.split(":", 1)[1]))
                return
            if data.startswith("delask:"):
                self.ask_delete(chat_id, message_id, callback_id, int(data.split(":", 1)[1]))
                return
            if data.startswith("delyes:"):
                deleted = self.store.delete_student(int(data.split(":", 1)[1]))
                self.answer_callback(callback_id, "Eliminado" if deleted else "No encontrado")
                self.edit_message(chat_id, message_id, self.format_students(), self.students_keyboard())
                return
            self.answer_callback(callback_id, "Accion no reconocida")
        except Exception as exc:
            self.answer_callback(callback_id, f"Error: {exc}")

    def request_student_id(self, chat_id: int, message_id: int, callback_id: str, action: str) -> None:
        labels = {
            "edit": "editar",
            "toggle": "activar/desactivar",
            "delete": "eliminar",
        }
        label = labels.get(action)
        if not label:
            self.answer_callback(callback_id, "Accion no reconocida")
            return
        self.pending_actions[chat_id] = action
        self.answer_callback(callback_id, "Envia el ID")
        self.edit_message(
            chat_id,
            message_id,
            "<b>ID requerido</b>\n"
            f"Envia solo el ID del alumno que quieres {label}.\n\n"
            "Ejemplo: <code>3</code>",
            self.cancel_action_keyboard(),
        )

    def handle_pending_action(self, chat_id: int, text: str) -> str | dict[str, Any]:
        action = self.pending_actions.pop(chat_id)
        if text.lower() in ("cancelar", "cancel", "no"):
            return {"text": self.format_students(), "reply_markup": self.students_keyboard()}
        try:
            student_id = int(text.strip())
        except ValueError:
            self.pending_actions[chat_id] = action
            return "<b>ID invalido</b>\nEnvia solo el numero de ID. Ejemplo: <code>3</code>"

        if action == "edit":
            student = self.store.get_student(student_id)
            if not student:
                return "Alumno no encontrado."
            return (
                "<b>Editar alumno</b>\n"
                "Copia, ajusta y envia:\n"
                f"<code>/edit {student['id']} {h(student['dni'])} {h(student['codigo'])} {h(student['nombre'] or '')}</code>"
            )
        if action == "toggle":
            student = self.store.get_student(student_id)
            if not student:
                return "Alumno no encontrado."
            updated = self.store.set_student_active(student_id, not bool(student["activo"]))
            state = "activado" if updated and updated["activo"] else "desactivado"
            return (
                f"<b>Alumno {state}</b>\n"
                + pre(f"ID     : {student_id}\nDNI    : {student['dni']}\nCodigo : {student['codigo']}")
            )
        if action == "delete":
            student = self.store.get_student(student_id)
            if not student:
                return "Alumno no encontrado."
            return {
                "text": (
                    "<b>Confirmar eliminacion</b>\n"
                    f"Alumno: <code>{h(student['dni'])}</code> <code>{h(student['codigo'])}</code>\n"
                    f"Nombre: {h(student['nombre'] or '-')}"
                ),
                "reply_markup": self.confirm_delete_keyboard(student_id),
            }
        return "Accion no reconocida."

    def toggle_student(self, chat_id: int, message_id: int, callback_id: str, student_id: int) -> None:
        student = self.store.get_student(student_id)
        if not student:
            self.answer_callback(callback_id, "Alumno no encontrado")
            self.edit_message(chat_id, message_id, self.format_students(), self.students_keyboard())
            return
        self.store.set_student_active(student_id, not bool(student["activo"]))
        self.answer_callback(callback_id, "Estado actualizado")
        self.edit_message(chat_id, message_id, self.format_students(), self.students_keyboard())

    def send_edit_template(self, chat_id: int, callback_id: str, student_id: int) -> None:
        student = self.store.get_student(student_id)
        if not student:
            self.answer_callback(callback_id, "Alumno no encontrado")
            return
        self.answer_callback(callback_id, "Plantilla enviada")
        self.send_message(
            chat_id,
            "<b>Editar alumno</b>\n"
            "Copia, ajusta y envia:\n"
            f"<code>/edit {student['id']} {h(student['dni'])} {h(student['codigo'])} {h(student['nombre'] or '')}</code>",
        )

    def ask_delete(self, chat_id: int, message_id: int, callback_id: str, student_id: int) -> None:
        student = self.store.get_student(student_id)
        if not student:
            self.answer_callback(callback_id, "Alumno no encontrado")
            self.edit_message(chat_id, message_id, self.format_students(), self.students_keyboard())
            return
        self.answer_callback(callback_id)
        self.edit_message(
            chat_id,
            message_id,
            "<b>Confirmar eliminacion</b>\n"
            f"Alumno: <code>{h(student['dni'])}</code> <code>{h(student['codigo'])}</code>\n"
            f"Nombre: {h(student['nombre'] or '-')}",
            self.confirm_delete_keyboard(student_id),
        )

    def handle_command(self, text: str) -> str | dict[str, Any]:
        parts = text.split()
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]

        if command in ("/start", "/help"):
            return {"text": self.help_text(), "reply_markup": self.main_keyboard()}
        if command == "/id":
            return "<b>Tu chat esta autorizado.</b>"
        if command == "/add":
            return self.add_student(args)
        if command == "/list":
            return {"text": self.format_students(), "reply_markup": self.students_keyboard()}
        if command == "/edit":
            return self.edit_student(args)
        if command in ("/delete", "/del"):
            return self.delete_student(args)
        if command == "/disable":
            return self.set_active(args, False)
        if command == "/enable":
            return self.set_active(args, True)
        if command == "/run":
            threading.Thread(target=self.runner.run_until_ready, daemon=True).start()
            return self.run_started_text()
        if command == "/attempts":
            return self.format_attempts()
        if command in ("/tickets", "/status"):
            return {"text": self.format_tickets(), "reply_markup": self.tickets_keyboard()}
        return "Comando no reconocido. Usa <code>/help</code>"

    def add_student(self, args: list[str]) -> str:
        if len(args) < 2:
            return "Uso: <code>/add DNI CODIGO Nombre opcional</code>"
        student = self.store.add_student(args[0], args[1], " ".join(args[2:]))
        return (
            "<b>Alumno guardado</b>\n"
            + pre(
                f"ID     : {student['id']}\n"
                f"DNI    : {student['dni']}\n"
                f"Codigo : {student['codigo']}\n"
                f"Nombre : {student['nombre'] or '-'}"
            )
        )

    def edit_student(self, args: list[str]) -> str:
        if len(args) < 3:
            return "Uso: <code>/edit ID DNI CODIGO Nombre opcional</code>"
        student = self.store.update_student(
            int(args[0]),
            dni=args[1],
            codigo=args[2],
            nombre=" ".join(args[3:]),
        )
        if not student:
            return "Alumno no encontrado."
        return (
            "<b>Alumno actualizado</b>\n"
            + pre(
                f"ID     : {student['id']}\n"
                f"DNI    : {student['dni']}\n"
                f"Codigo : {student['codigo']}\n"
                f"Nombre : {student['nombre'] or '-'}"
            )
        )

    def delete_student(self, args: list[str]) -> str:
        if len(args) != 1:
            return "Uso: <code>/delete ID</code>"
        deleted = self.store.delete_student(int(args[0]))
        return "<b>Alumno eliminado.</b>" if deleted else "Alumno no encontrado."

    def set_active(self, args: list[str], active: bool) -> str:
        if len(args) != 1:
            return "Uso: <code>/enable ID</code>" if active else "Uso: <code>/disable ID</code>"
        student = self.store.set_student_active(int(args[0]), active)
        if not student:
            return "Alumno no encontrado."
        state = "activado" if active else "desactivado"
        return (
            f"<b>Alumno {state}</b>\n"
            + pre(f"ID     : {student['id']}\nDNI    : {student['dni']}\nCodigo : {student['codigo']}")
        )

    def format_students(self) -> str:
        students = self.store.list_students()
        if not students:
            return "<b>Alumnos</b>\n\nNo hay alumnos registrados."

        active_count = sum(1 for student in students if student["activo"])
        lines = [
            "<b>Alumnos registrados</b>",
            pre(f"Total    : {len(students)}\nActivos  : {active_count}\nInactivos: {len(students) - active_count}"),
        ]
        table = ["ID  EST       DNI        CODIGO"]
        for student in students:
            table.append(
                f"{student['id']:<3} {status_label(student['activo']):<9} {student['dni']:<10} {student['codigo']}"
            )
            if student["nombre"]:
                table.append(f"    {student['nombre']}")
        lines.append(pre("\n".join(table)))
        lines.append("<i>Usa los botones para editar, activar/desactivar o eliminar.</i>")
        return "\n".join(lines)

    def format_attempts(self) -> str:
        attempts = self.store.recent_attempts(limit=10)
        if not attempts:
            return "<b>Ultimos intentos</b>\n\nNo hay intentos registrados."
        table = ["FECHA                DNI        ESTADO              TICKET"]
        for attempt in attempts:
            table.append(
                f"{attempt['created_at']:<19} {attempt['dni']:<10} "
                f"{attempt['status']:<19} {attempt['ticket_codigo'] or '-'}"
            )
            if attempt["error"]:
                table.append(f"  error: {attempt['error']}")
        return "<b>Ultimos intentos</b>\n" + pre("\n".join(table))

    def format_tickets(self) -> str:
        today = datetime.now(self.config.timezone).date().isoformat()
        rows = self.store.latest_attempts_by_student(today)
        if not rows:
            return "<b>Tickets de hoy</b>\n\nNo hay alumnos registrados."

        with_ticket = []
        without_ticket = []
        inactive = []
        for row in rows:
            label = f"{row['student_id']}. {row['dni']} {row['codigo']}"
            if row["nombre"]:
                label += f" - {row['nombre']}"
            if not row["activo"]:
                inactive.append(label)
            elif row["ticket_codigo"]:
                with_ticket.append(f"{label} -> {row['ticket_codigo']}")
            else:
                reason = row["status"] or "sin intento hoy"
                if row["error"]:
                    reason = f"{reason}: {row['error']}"
                without_ticket.append(f"{label} -> {reason}")

        no_quota_count = sum(1 for row in rows if row["status"] == "no_quota")
        lines = [
            "<b>Tickets de hoy</b>",
            pre(
                f"Fecha     : {today}\n"
                f"Con ticket: {len(with_ticket)}\n"
                f"Sin ticket: {len(without_ticket)}\n"
                f"Sin cupos : {no_quota_count}\n"
                f"Inactivos : {len(inactive)}"
            ),
            "<b>Con ticket</b>",
            pre("\n".join(with_ticket) if with_ticket else "Ninguno"),
            "<b>Sin ticket</b>",
            pre("\n".join(without_ticket) if without_ticket else "Ninguno"),
        ]
        if inactive:
            lines.extend(["<b>Inactivos</b>", pre("\n".join(inactive))])
        return "\n".join(lines)

    def send_run_report(self, result: dict[str, Any]) -> None:
        text = self.format_run_report(result)
        for chat_id in self.config.telegram_admin_ids:
            try:
                self.send_message(chat_id, text, self.tickets_keyboard())
            except Exception as exc:
                print(f"Telegram report error for {chat_id}: {hide_token(str(exc), self.config.telegram_bot_token)}")

    def format_run_report(self, result: dict[str, Any]) -> str:
        final_result = result.get("last_result", result)
        results = final_result.get("results", [])
        ok = [item for item in results if item.get("status") == "ok"]
        skipped = [item for item in results if item.get("status") == "skipped_ticket_exists"]
        no_quota = [item for item in results if item.get("status") == "no_quota"]
        failed = [
            item
            for item in results
            if item.get("status") not in ("ok", "skipped_ticket_exists", "no_quota")
        ]

        now = datetime.now(self.config.timezone)
        start_text = (
            "07:00 en punto"
            if self.config.start_before_minutes == 0
            else f"-{self.config.start_before_minutes} min"
        )
        window = (
            f"Objetivo : {self.config.run_at}\n"
            f"Inicio   : {start_text}\n"
            f"Cierre   : +{self.config.stop_after_minutes} min\n"
            f"Reporte  : {now.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        lines = [
            "<b>Reporte de ejecucion</b>",
            pre(window),
            pre(
                f"Estado       : {result.get('status')}\n"
                f"Nuevos ticket: {len(ok)}\n"
                f"Ya tenian    : {len(skipped)}\n"
                f"Sin cupos    : {len(no_quota)}\n"
                f"Otros fallos : {len(failed)}"
            ),
        ]
        if ok:
            lines.extend(["<b>Nuevos tickets</b>", pre(self.result_lines(ok))])
        if skipped:
            lines.extend(["<b>Ya tenian ticket</b>", pre(self.result_lines(skipped))])
        if no_quota:
            lines.extend(
                [
                    "<b>Sin cupos</b>",
                    pre(self.result_lines(no_quota, include_status=True)),
                    "<i>Se detuvieron los reintentos para no seguir enviando solicitudes.</i>",
                ]
            )
        if failed:
            lines.extend(["<b>Sin ticket</b>", pre(self.result_lines(failed, include_status=True))])
        if not results and result.get("status") == "busy":
            lines.append(pre(result.get("message", "Ejecucion en curso")))
        return "\n".join(lines)

    def result_lines(self, results: list[dict[str, Any]], include_status: bool = False) -> str:
        lines = []
        for item in results:
            ticket = item.get("ticket_codigo") or "-"
            base = f"{item.get('dni')} {item.get('codigo')} -> {ticket}"
            if include_status:
                base += f" ({item.get('status')})"
                if item.get("error"):
                    base += f" {item.get('error')}"
            lines.append(base)
        return "\n".join(lines)

    def run_started_text(self) -> str:
        start_text = (
            "desde las 07:00 en punto"
            if self.config.start_before_minutes == 0
            else f"desde {self.config.start_before_minutes} min antes"
        )
        return (
            "<b>Ejecucion iniciada</b>\n"
            + pre(
                "Se registraran solo alumnos activos sin ticket de hoy.\n"
                f"Ventana: {start_text} hasta +{self.config.stop_after_minutes} min."
            )
            + "\nRevisa <code>/tickets</code> en unos segundos."
        )

    def students_keyboard(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Editar", "callback_data": "action:edit"},
                    {"text": "Activar/Desactivar", "callback_data": "action:toggle"},
                ],
                [{"text": "Eliminar", "callback_data": "action:delete"}],
                [
                    {"text": "Actualizar lista", "callback_data": "students"},
                    {"text": "Ver tickets", "callback_data": "tickets"},
                ],
            ]
        }

    def tickets_keyboard(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Actualizar tickets", "callback_data": "tickets"},
                    {"text": "Ejecutar faltantes", "callback_data": "run"},
                ],
                [{"text": "Ver alumnos", "callback_data": "students"}],
            ]
        }

    def confirm_delete_keyboard(self, student_id: int) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Si, eliminar", "callback_data": f"delyes:{student_id}"},
                    {"text": "Cancelar", "callback_data": "students"},
                ]
            ]
        }

    def cancel_action_keyboard(self) -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": "Cancelar", "callback_data": "students"}]]}

    def main_keyboard(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "Ver alumnos", "callback_data": "students"},
                    {"text": "Ver tickets", "callback_data": "tickets"},
                ],
                [{"text": "Ejecutar faltantes", "callback_data": "run"}],
            ]
        }

    def help_text(self) -> str:
        return (
            "<b>Comedor service</b>\n"
            "Gestion de alumnos y tickets desde Telegram.\n\n"
            "<b>Comandos</b>\n"
            "<code>/add DNI CODIGO Nombre opcional</code>\n"
            "<code>/list</code>\n"
            "<code>/edit ID DNI CODIGO Nombre opcional</code>\n"
            "<code>/delete ID</code>\n"
            "<code>/disable ID</code>\n"
            "<code>/enable ID</code>\n"
            "<code>/run</code>\n"
            "<code>/attempts</code>\n"
            "<code>/tickets</code>\n"
            "<code>/id</code>"
        )
