"""SQLite storage for reminders."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "reminders.db"

STATUS_PENDING = "Ожидает"
STATUS_DONE = "Готово"
STATUS_OVERDUE = "Просрочено"
STATUS_CANCELLED = "Отменено"

ALL_STATUSES = (
    STATUS_PENDING,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_CANCELLED,
)

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def format_dt(value: datetime) -> str:
    return value.strftime(DATETIME_FMT)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FMT)


@dataclass
class Reminder:
    id: int
    title: str
    description: str
    due_at: datetime
    status: str
    notified: bool
    created_at: datetime

    @property
    def due_at_display(self) -> str:
        return self.due_at.strftime("%d.%m.%Y %H:%M")


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        due_at=parse_dt(row["due_at"]),
        status=row["status"],
        notified=bool(row["notified"]),
        created_at=parse_dt(row["created_at"]),
    )


class ReminderStore:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Ожидает'
                        CHECK (status IN ('Ожидает', 'Готово', 'Просрочено', 'Отменено')),
                    notified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due_at ON reminders(due_at)"
            )

    def add(self, title: str, description: str, due_at: datetime) -> int:
        title = title.strip()
        if not title:
            raise ValueError("Заголовок не может быть пустым")
        created = now_local()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminders (title, description, due_at, status, notified, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (title, description.strip(), format_dt(due_at), STATUS_PENDING, format_dt(created)),
            )
            return int(cursor.lastrowid)

    def delete(self, reminder_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def set_status(self, reminder_id: int, status: str) -> None:
        if status not in ALL_STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?",
                (status, reminder_id),
            )

    def mark_notified(self, reminder_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET notified = 1 WHERE id = ?",
                (reminder_id,),
            )

    def reschedule(self, reminder_id: int, due_at: datetime) -> None:
        due_at = due_at.replace(second=0, microsecond=0)
        if due_at <= now_local():
            raise ValueError("Новое время должно быть позже текущего")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET due_at = ?, status = ?, notified = 0
                WHERE id = ?
                """,
                (format_dt(due_at), STATUS_PENDING, reminder_id),
            )

    def get(self, reminder_id: int) -> Optional[Reminder]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
        return _row_to_reminder(row) if row else None

    def list(self, status: Optional[str] = None) -> list[Reminder]:
        query = "SELECT * FROM reminders"
        params: tuple = ()
        if status:
            if status not in ALL_STATUSES:
                raise ValueError(f"Неизвестный статус: {status}")
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY due_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def mark_overdue(self, as_of: Optional[datetime] = None) -> list[Reminder]:
        """Переводит ожидающие напоминания с прошедшим временем в «Просрочено»."""
        moment = format_dt(as_of or now_local())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = ?
                WHERE status = ? AND due_at <= ?
                """,
                (STATUS_OVERDUE, STATUS_PENDING, moment),
            )
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE status = ? AND due_at <= ? AND notified = 0
                ORDER BY due_at ASC
                """,
                (STATUS_OVERDUE, moment),
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]
