"""Local result persistence. Swap this repository for a hosted store later."""

import sqlite3
from contextlib import closing
from pathlib import Path

from backend.models import ComparisonResult


class ComparisonStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS comparisons (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def save(self, result: ComparisonResult) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO comparisons VALUES (?, ?)", (result.id, result.model_dump_json()))

    def get(self, comparison_id: str) -> ComparisonResult | None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            row = connection.execute("SELECT payload FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
        return ComparisonResult.model_validate_json(row[0]) if row else None

    def healthy(self) -> bool:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("SELECT id FROM comparisons LIMIT 1")
        return True
