"""Accès SQLite. La base valopti.db est générée par etl/build_db.py."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("VALOPTI_DB", ROOT / "data" / "valopti.db"))


def _dict_factory(cur: sqlite3.Cursor, row: tuple) -> dict:
    return {d[0]: v for d, v in zip(cur.description, row)}


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(f"Base introuvable : {DB_PATH}. Lancez d'abord : python -m etl.build_db")
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = _dict_factory
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def get_db() -> Iterator[sqlite3.Connection]:
    """Dépendance FastAPI : une connexion par requête."""
    con = connect()
    try:
        yield con
    finally:
        con.close()


def rows(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return con.execute(sql, params).fetchall()


def one(con: sqlite3.Connection, sql: str, params=()) -> dict | None:
    return con.execute(sql, params).fetchone()
