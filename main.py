"""Точка входа: напоминалка для Windows."""

from __future__ import annotations

import argparse

from gui import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Напоминания для Windows")
    parser.add_argument(
        "--add",
        action="store_true",
        help="Сразу поставить курсор в форму нового напоминания",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(focus_add=args.add)
