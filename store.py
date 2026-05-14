import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dni TEXT NOT NULL,
                codigo TEXT NOT NULL,
                nombre TEXT DEFAULT '',
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(dni, codigo)
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                run_date TEXT NOT NULL,
                status TEXT NOT NULL,
                http_status INTEGER,
                ticket_codigo TEXT,
                response_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(student_id) REFERENCES students(id)
            );
            """
        )


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.lock = threading.Lock()

    def list_students(self) -> list[dict[str, Any]]:
        with self.lock, connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students ORDER BY id"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def add_student(self, dni: str, codigo: str, nombre: str = "") -> dict[str, Any]:
        dni = dni.strip()
        codigo = codigo.strip()
        nombre = nombre.strip()
        if not dni or not codigo:
            raise ValueError("dni y codigo son obligatorios")
        with self.lock, connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO students (dni, codigo, nombre, activo)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(dni, codigo) DO UPDATE SET
                    nombre = excluded.nombre,
                    activo = 1
                """,
                (dni, codigo, nombre),
            )
            row = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students WHERE dni = ? AND codigo = ?",
                (dni, codigo),
            ).fetchone()
        return row_to_dict(row)

    def set_student_active(self, student_id: int, active: bool) -> dict[str, Any] | None:
        with self.lock, connect(self.db_path) as conn:
            conn.execute("UPDATE students SET activo = ? WHERE id = ?", (1 if active else 0, student_id))
            row = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students WHERE id = ?",
                (student_id,),
            ).fetchone()
        return row_to_dict(row) if row else None

    def update_student(
        self,
        student_id: int,
        dni: str | None = None,
        codigo: str | None = None,
        nombre: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_student(student_id)
        if not current:
            return None
        next_dni = (dni if dni is not None else current["dni"]).strip()
        next_codigo = (codigo if codigo is not None else current["codigo"]).strip()
        next_nombre = (nombre if nombre is not None else current["nombre"]).strip()
        if not next_dni or not next_codigo:
            raise ValueError("dni y codigo no pueden quedar vacios")
        with self.lock, connect(self.db_path) as conn:
            conn.execute(
                "UPDATE students SET dni = ?, codigo = ?, nombre = ? WHERE id = ?",
                (next_dni, next_codigo, next_nombre, student_id),
            )
            row = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students WHERE id = ?",
                (student_id,),
            ).fetchone()
        return row_to_dict(row) if row else None

    def delete_student(self, student_id: int) -> bool:
        with self.lock, connect(self.db_path) as conn:
            conn.execute("DELETE FROM attempts WHERE student_id = ?", (student_id,))
            cursor = conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        return cursor.rowcount > 0

    def get_student(self, student_id: int) -> dict[str, Any] | None:
        with self.lock, connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students WHERE id = ?",
                (student_id,),
            ).fetchone()
        return row_to_dict(row) if row else None

    def active_students(self) -> list[dict[str, Any]]:
        with self.lock, connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, dni, codigo, nombre, activo, created_at FROM students WHERE activo = 1 ORDER BY id"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def ticket_for_today(self, student_id: int, run_date: str) -> str | None:
        with self.lock, connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT ticket_codigo
                FROM attempts
                WHERE student_id = ?
                    AND run_date = ?
                    AND ticket_codigo IS NOT NULL
                    AND ticket_codigo != ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (student_id, run_date),
            ).fetchone()
        return row["ticket_codigo"] if row else None

    def record_attempt(
        self,
        student_id: int,
        run_date: str,
        status: str,
        http_status: int | None = None,
        ticket_codigo: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.lock, connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO attempts (
                    student_id, run_date, status, http_status, ticket_codigo, response_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    run_date,
                    status,
                    http_status,
                    ticket_codigo,
                    json.dumps(response_json, ensure_ascii=False) if response_json else None,
                    error,
                ),
            )

    def recent_attempts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    attempts.id,
                    attempts.student_id,
                    students.dni,
                    students.codigo,
                    students.nombre,
                    attempts.run_date,
                    attempts.status,
                    attempts.http_status,
                    attempts.ticket_codigo,
                    attempts.error,
                    attempts.created_at
                FROM attempts
                JOIN students ON students.id = attempts.student_id
                ORDER BY attempts.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def latest_attempts_by_student(self, run_date: str) -> list[dict[str, Any]]:
        with self.lock, connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    students.id AS student_id,
                    students.dni,
                    students.codigo,
                    students.nombre,
                    students.activo,
                    attempts.status,
                    attempts.ticket_codigo,
                    attempts.error,
                    attempts.created_at
                FROM students
                LEFT JOIN (
                    SELECT a.*
                    FROM attempts a
                    JOIN (
                        SELECT student_id, MAX(id) AS max_id
                        FROM attempts
                        WHERE run_date = ?
                        GROUP BY student_id
                    ) latest ON latest.max_id = a.id
                ) attempts ON attempts.student_id = students.id
                ORDER BY students.id
                """,
                (run_date,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]
