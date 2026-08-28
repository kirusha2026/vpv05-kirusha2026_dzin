"""Tkinter UI for the reminder app."""

from __future__ import annotations

from datetime import datetime, timedelta
from tkinter import BOTH, END, LEFT, RIGHT, WORD, StringVar, Tk, Toplevel, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from database import (
    ALL_STATUSES,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_OVERDUE,
    STATUS_PENDING,
    Reminder,
    ReminderStore,
    now_local,
)
from notifications import NotificationService


FILTER_ALL = "Все"


class ReminderApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.store = ReminderStore()
        self.filter_var = StringVar(value=FILTER_ALL)
        self._popup_open_ids: set[int] = set()

        self._build_ui()
        self.notifier = NotificationService(self.store, on_due=self._on_reminder_due)
        self.notifier.start(self.root)
        self.refresh_list()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.title("Напоминания")
        self.root.geometry("920x620")
        self.root.minsize(780, 520)

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        # На Windows тема перебивает цвета тегов Treeview — оставляем только selected
        style.map(
            "Treeview",
            foreground=[
                elm
                for elm in style.map("Treeview", query_opt="foreground")
                if elm[:2] != ("!disabled", "!selected")
            ],
            background=[
                elm
                for elm in style.map("Treeview", query_opt="background")
                if elm[:2] != ("!disabled", "!selected")
            ],
        )

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(outer, text="Напоминания", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Уведомления срабатывают даже если окно свёрнуто.",
        ).pack(anchor="w", pady=(0, 10))

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill=BOTH, expand=True)

        form = ttk.Labelframe(body, text="Новое напоминание", padding=10)
        list_frame = ttk.Labelframe(body, text="Список", padding=10)
        body.add(form, weight=1)
        body.add(list_frame, weight=2)

        ttk.Label(form, text="Заголовок").pack(anchor="w")
        self.title_var = StringVar()
        self.title_entry = ttk.Entry(form, textvariable=self.title_var)
        self.title_entry.pack(fill="x", pady=(0, 8))

        ttk.Label(form, text="Описание").pack(anchor="w")
        self.description = ScrolledText(form, height=8, wrap=WORD, font=("Segoe UI", 10))
        self.description.pack(fill=BOTH, expand=True, pady=(0, 8))

        when = ttk.Frame(form)
        when.pack(fill="x", pady=(0, 8))
        ttk.Label(when, text="Дата (ДД.ММ.ГГГГ)").grid(row=0, column=0, sticky="w")
        ttk.Label(when, text="Время (ЧЧ:ММ)").grid(row=0, column=1, sticky="w", padx=(8, 0))

        default = now_local() + timedelta(minutes=5)
        self.date_var = StringVar(value=default.strftime("%d.%m.%Y"))
        self.time_var = StringVar(value=default.strftime("%H:%M"))
        ttk.Entry(when, textvariable=self.date_var, width=16).grid(row=1, column=0, sticky="ew")
        ttk.Entry(when, textvariable=self.time_var, width=10).grid(row=1, column=1, sticky="ew", padx=(8, 0))
        when.columnconfigure(0, weight=1)
        when.columnconfigure(1, weight=1)

        ttk.Button(form, text="Добавить напоминание", command=self.add_reminder).pack(
            fill="x", pady=(4, 0)
        )

        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Статус:").pack(side=LEFT)
        self.filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=(FILTER_ALL, *ALL_STATUSES),
            state="readonly",
            width=16,
        )
        self.filter_box.pack(side=LEFT, padx=6)
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())
        ttk.Button(toolbar, text="Обновить", command=self.refresh_list).pack(side=LEFT)

        columns = ("due", "status", "title")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("due", text="Дата и время")
        self.tree.heading("status", text="Статус")
        self.tree.heading("title", text="Заголовок")
        self.tree.column("due", width=140, stretch=False)
        self.tree.column("status", width=110, stretch=False)
        self.tree.column("title", width=280)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.tag_configure(STATUS_DONE, foreground="#15803d")
        self.tree.tag_configure(STATUS_OVERDUE, foreground="#dc2626")
        self.tree.tag_configure(STATUS_PENDING, foreground="#2563eb")
        self.tree.tag_configure(STATUS_CANCELLED, foreground="#c2410c")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_details())
        self.tree.bind("<Double-1>", lambda _e: self._show_selected_popup())

        actions = ttk.Frame(list_frame)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Готово", command=lambda: self._set_selected(STATUS_DONE)).pack(
            side=LEFT
        )
        ttk.Button(
            actions, text="Отменено", command=lambda: self._set_selected(STATUS_CANCELLED)
        ).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Удалить", command=self.delete_selected).pack(side=RIGHT)

        self.details = ScrolledText(list_frame, height=6, wrap=WORD, font=("Segoe UI", 10), state="disabled")
        self.details.pack(fill="x", pady=(8, 0))

        self.status_var = StringVar(value="Готово")
        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w", pady=(8, 0))

    def _parse_due(self) -> datetime:
        date_text = self.date_var.get().strip()
        time_text = self.time_var.get().strip()
        try:
            return datetime.strptime(f"{date_text} {time_text}", "%d.%m.%Y %H:%M")
        except ValueError as exc:
            raise ValueError("Укажите дату как ДД.ММ.ГГГГ и время как ЧЧ:ММ") from exc

    def add_reminder(self) -> None:
        title = self.title_var.get().strip()
        description = self.description.get("1.0", END).strip()
        try:
            due_at = self._parse_due()
            reminder_id = self.store.add(title, description, due_at)
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        self.title_var.set("")
        self.description.delete("1.0", END)
        later = now_local() + timedelta(minutes=5)
        self.date_var.set(later.strftime("%d.%m.%Y"))
        self.time_var.set(later.strftime("%H:%M"))
        self.refresh_list()
        self.status_var.set(f"Добавлено напоминание №{reminder_id}")

    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _set_selected(self, status: str) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            messagebox.showinfo("Напоминания", "Выберите напоминание в списке.", parent=self.root)
            return
        self.store.set_status(reminder_id, status)
        self.refresh_list()
        self.status_var.set(f"Статус изменён на «{status}»")

    def delete_selected(self) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            messagebox.showinfo("Напоминания", "Выберите напоминание в списке.", parent=self.root)
            return
        reminder = self.store.get(reminder_id)
        label = reminder.title if reminder else str(reminder_id)
        if not messagebox.askyesno("Удалить", f"Удалить «{label}»?", parent=self.root):
            return
        self.store.delete(reminder_id)
        self.refresh_list()
        self.status_var.set("Напоминание удалено")

    def refresh_list(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        status = self.filter_var.get()
        reminders = self.store.list(None if status == FILTER_ALL else status)
        for reminder in reminders:
            self.tree.insert(
                "",
                END,
                iid=str(reminder.id),
                values=(reminder.due_at_display, reminder.status, reminder.title),
                tags=(reminder.status,),
            )
        self._set_details("")
        self.status_var.set(f"Показано: {len(reminders)}")

    def _show_selected_details(self) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            self._set_details("")
            return
        reminder = self.store.get(reminder_id)
        if not reminder:
            self._set_details("")
            return
        text = (
            f"{reminder.title}\n"
            f"Статус: {reminder.status}\n"
            f"Срабатывание: {reminder.due_at_display}\n\n"
            f"{reminder.description or 'Без описания'}"
        )
        self._set_details(text)

    def _set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", END)
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _show_selected_popup(self) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            return
        reminder = self.store.get(reminder_id)
        if reminder:
            self.show_popup(reminder)

    def _on_reminder_due(self, reminder: Reminder) -> None:
        self.refresh_list()
        self.show_popup(reminder, urgent=True)
        self.status_var.set(f"Сработало: {reminder.title}")

    def show_popup(self, reminder: Reminder, urgent: bool = False) -> None:
        if reminder.id in self._popup_open_ids:
            return
        self._popup_open_ids.add(reminder.id)

        popup = Toplevel(self.root)
        popup.title("Напоминание" if urgent else "Просмотр")
        popup.geometry("460x460")
        popup.minsize(420, 400)
        popup.attributes("-topmost", True)
        if urgent:
            try:
                popup.attributes("-topmost", True)
                popup.lift()
                popup.focus_force()
                self.root.deiconify()
            except Exception:
                pass

        frame = ttk.Frame(popup, padding=16)
        frame.pack(fill=BOTH, expand=True)
        ttk.Label(frame, text=reminder.title, style="Title.TLabel", wraplength=420).pack(anchor="w")
        ttk.Label(frame, text=f"{reminder.due_at_display}  ·  {reminder.status}").pack(
            anchor="w", pady=(4, 10)
        )
        body = ScrolledText(frame, wrap=WORD, height=6, font=("Segoe UI", 10))
        body.pack(fill=BOTH, expand=True)
        body.insert("1.0", reminder.description or "Без описания")
        body.configure(state="disabled")

        snooze = ttk.Labelframe(frame, text="Перенести", padding=8)
        snooze.pack(fill="x", pady=(12, 0))

        later = now_local() + timedelta(minutes=10)
        custom_date = StringVar(value=later.strftime("%d.%m.%Y"))
        custom_time = StringVar(value=later.strftime("%H:%M"))

        def close() -> None:
            self._popup_open_ids.discard(reminder.id)
            popup.destroy()

        def mark(status: str) -> None:
            self.store.set_status(reminder.id, status)
            self.refresh_list()
            close()

        def postpone_to(due_at: datetime) -> None:
            try:
                self.store.reschedule(reminder.id, due_at)
            except ValueError as exc:
                messagebox.showerror("Перенос", str(exc), parent=popup)
                return
            self.refresh_list()
            self.status_var.set(
                f"Перенесено на {due_at.strftime('%d.%m.%Y %H:%M')}: {reminder.title}"
            )
            close()

        def postpone_minutes(minutes: int) -> None:
            postpone_to(now_local() + timedelta(minutes=minutes))

        def postpone_custom() -> None:
            date_text = custom_date.get().strip()
            time_text = custom_time.get().strip()
            try:
                due_at = datetime.strptime(f"{date_text} {time_text}", "%d.%m.%Y %H:%M")
            except ValueError:
                messagebox.showerror(
                    "Перенос",
                    "Укажите дату как ДД.ММ.ГГГГ и время как ЧЧ:ММ",
                    parent=popup,
                )
                return
            postpone_to(due_at)

        quick = ttk.Frame(snooze)
        quick.pack(fill="x")
        ttk.Button(quick, text="+10 мин", command=lambda: postpone_minutes(10)).pack(
            side=LEFT, expand=True, fill="x"
        )
        ttk.Button(quick, text="+30 мин", command=lambda: postpone_minutes(30)).pack(
            side=LEFT, expand=True, fill="x", padx=6
        )
        ttk.Button(quick, text="+60 мин", command=lambda: postpone_minutes(60)).pack(
            side=LEFT, expand=True, fill="x"
        )

        custom = ttk.Frame(snooze)
        custom.pack(fill="x", pady=(8, 0))
        ttk.Label(custom, text="Дата").grid(row=0, column=0, sticky="w")
        ttk.Label(custom, text="Время").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Entry(custom, textvariable=custom_date, width=14).grid(row=1, column=0, sticky="ew")
        ttk.Entry(custom, textvariable=custom_time, width=8).grid(
            row=1, column=1, sticky="ew", padx=(8, 0)
        )
        ttk.Button(custom, text="Перенести", command=postpone_custom).grid(
            row=1, column=2, sticky="ew", padx=(8, 0)
        )
        custom.columnconfigure(0, weight=1)
        custom.columnconfigure(1, weight=1)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))

        ttk.Button(buttons, text="Готово", command=lambda: mark(STATUS_DONE)).pack(side=LEFT)
        ttk.Button(buttons, text="Отменено", command=lambda: mark(STATUS_CANCELLED)).pack(
            side=LEFT, padx=6
        )
        ttk.Button(buttons, text="Закрыть", command=close).pack(side=RIGHT)
        popup.protocol("WM_DELETE_WINDOW", close)

        if urgent:
            popup.after(100, lambda: popup.bell())

    def focus_new_reminder(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.title_entry.focus_set()

    def _on_close(self) -> None:
        self.notifier.stop()
        self.root.destroy()


def run(focus_add: bool = False) -> None:
    root = Tk()
    app = ReminderApp(root)
    if focus_add:
        root.after(200, app.focus_new_reminder)
    root.mainloop()
