"""SQLite storage for reminders."""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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

REPEAT_NONE = ""
REPEAT_DAILY = "daily"
REPEAT_WEEKLY = "weekly"
REPEAT_MONTHLY = "monthly"

REPEAT_LABELS = {
    REPEAT_DAILY: "Каждый день",
    REPEAT_WEEKLY: "Каждую неделю",
    REPEAT_MONTHLY: "Каждый месяц",
}

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def format_dt(value: datetime) -> str:
    return value.strftime(DATETIME_FMT)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FMT)


def parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_FMT).date()


def advance_due(due_at: datetime, rule: str) -> datetime:
    if rule == REPEAT_DAILY:
        return due_at + timedelta(days=1)
    if rule == REPEAT_WEEKLY:
        return due_at + timedelta(weeks=1)
    if rule == REPEAT_MONTHLY:
        month = due_at.month + 1
        year = due_at.year
        if month > 12:
            month = 1
            year += 1
        day = min(due_at.day, calendar.monthrange(year, month)[1])
        return due_at.replace(year=year, month=month, day=day)
    raise ValueError(f"Неизвестная регулярность: {rule}")


@dataclass
class Reminder:
    id: int
    title: str
    description: str
    due_at: datetime
    status: str
    notified: bool
    created_at: datetime
    repeat_rule: str = REPEAT_NONE
    repeat_until: Optional[date] = None

    @property
    def due_at_display(self) -> str:
        return self.due_at.strftime("%d.%m.%Y %H:%M")

    @property
    def is_repeating(self) -> bool:
        return bool(self.repeat_rule)

    @property
    def repeat_display(self) -> str:
        if not self.repeat_rule:
            return "Нет"
        label = REPEAT_LABELS.get(self.repeat_rule, self.repeat_rule)
        if self.repeat_until:
            return f"{label} до {self.repeat_until.strftime('%d.%m.%Y')}"
        return label

    def next_occurrence(self) -> Optional[datetime]:
        if not self.repeat_rule:
            return None
        nxt = advance_due(self.due_at, self.repeat_rule)
        if self.repeat_until and nxt.date() > self.repeat_until:
            return None
        return nxt


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    keys = row.keys()
    until_raw = row["repeat_until"] if "repeat_until" in keys else ""
    return Reminder(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        due_at=parse_dt(row["due_at"]),
        status=row["status"],
        notified=bool(row["notified"]),
        created_at=parse_dt(row["created_at"]),
        repeat_rule=(row["repeat_rule"] if "repeat_rule" in keys else "") or REPEAT_NONE,
        repeat_until=parse_date(until_raw) if until_raw else None,
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
                    created_at TEXT NOT NULL,
                    repeat_rule TEXT NOT NULL DEFAULT '',
                    repeat_until TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
            }
            if "repeat_rule" not in columns:
                conn.execute(
                    "ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''"
                )
            if "repeat_until" not in columns:
                conn.execute(
                    "ALTER TABLE reminders ADD COLUMN repeat_until TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due_at ON reminders(due_at)"
            )

    def add(
        self,
        title: str,
        description: str,
        due_at: datetime,
        repeat_rule: str = REPEAT_NONE,
        repeat_until: Optional[date] = None,
    ) -> int:
        title = title.strip()
        if not title:
            raise ValueError("Заголовок не может быть пустым")
        if repeat_rule and repeat_rule not in REPEAT_LABELS:
            raise ValueError("Укажите регулярность повтора")
        if repeat_rule and repeat_until is None:
            raise ValueError("Для повтора укажите конечную дату")
        if repeat_until and due_at.date() > repeat_until:
            raise ValueError("Первое срабатывание не может быть позже конечной даты")
        until_text = repeat_until.strftime(DATE_FMT) if repeat_until else ""
        created = now_local()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminders (
                    title, description, due_at, status, notified, created_at,
                    repeat_rule, repeat_until
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    title,
                    description.strip(),
                    format_dt(due_at),
                    STATUS_PENDING,
                    format_dt(created),
                    repeat_rule or REPEAT_NONE,
                    until_text,
                ),
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

    def complete(self, reminder_id: int) -> Optional[datetime]:
        """Отметить выполненным. У повтора ставит следующее срабатывание, если оно до конечной даты."""
        reminder = self.get(reminder_id)
        if reminder is None:
            return None
        nxt = reminder.next_occurrence()
        if nxt is None:
            self.set_status(reminder_id, STATUS_DONE)
            return None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET due_at = ?, status = ?, notified = 0
                WHERE id = ?
                """,
                (format_dt(nxt), STATUS_PENDING, reminder_id),
            )
        return nxt

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
        reminder = self.get(reminder_id)
        if reminder and reminder.repeat_until and due_at.date() > reminder.repeat_until:
            raise ValueError("Нельзя перенести позже конечной даты повтора")
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

    def counts(self) -> dict[str, int]:
        result = {"Всего": 0, **{status: 0 for status in ALL_STATUSES}}
        with self._connect() as conn:
            result["Всего"] = int(
                conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
            )
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM reminders GROUP BY status"
            ).fetchall()
        for row in rows:
            result[row["status"]] = int(row["n"])
        return result

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
