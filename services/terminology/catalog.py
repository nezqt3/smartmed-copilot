"""Read-only search over the pinned Chinese clinical diagnosis list."""

import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

SOURCE_SHA256 = "435ccd9376fe71920d26d399d831f499a473ae5632654c2e1d6ae1e2d97e9951"
SOURCE_URL = "https://wjw.fj.gov.cn/xxgk/fgwj/zxwj/201904/t20190412_4848943.htm"
ADDENDUM_URL = "https://www.nhc.gov.cn/yzygj/c100068/202002/858a64332b294a6183fbf8ec4a258d70.shtml"
ADDENDUM_SHA256 = "868a2d3b0e719ab62118b1efef328ac6cae9db77823389ade1c98e6242b552d0"
EXPECTED_BASE_ROWS = 37_289
EXPECTED_ROWS = 37_294


def normalize(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def source() -> dict:
    return {
        "edition": "国家临床版2.0（2019）+ 新冠相关 ICD-10 补充代码（2020）",
        "publication_url": SOURCE_URL,
        "file_sha256": SOURCE_SHA256,
        "published_year": 2020,
        "addendum_url": ADDENDUM_URL,
        "addendum_sha256": ADDENDUM_SHA256,
        "complete_2022_edition": False,
        "current_for_clinical_use": False,
        "review_required": True,
    }


class Catalog:
    def __init__(self, path: Path):
        self.path = path

    def connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def ready(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            with closing(self.connection()) as db:
                metadata = dict(db.execute("SELECT key, value FROM metadata").fetchall())
                return (metadata.get("source_sha256") == SOURCE_SHA256
                        and metadata.get("addendum_sha256") == ADDENDUM_SHA256)
        except sqlite3.Error:
            return False

    def count(self) -> int:
        with closing(self.connection()) as db:
            return db.execute("SELECT count(*) FROM diagnoses").fetchone()[0]

    def search(self, query: str, limit: int) -> tuple[list[dict], bool]:
        needle = normalize(query)
        with closing(self.connection()) as db:
            rows = db.execute(
                """
                SELECT source_file, source_row, primary_code, additional_code, name
                FROM diagnoses
                WHERE instr(primary_key, :needle) > 0
                   OR instr(additional_key, :needle) > 0
                   OR instr(name_key, :needle) > 0
                ORDER BY CASE
                    WHEN primary_key = :needle THEN 0
                    WHEN additional_key = :needle THEN 1
                    WHEN name_key = :needle THEN 2
                    WHEN substr(primary_key, 1, length(:needle)) = :needle THEN 3
                    WHEN substr(additional_key, 1, length(:needle)) = :needle THEN 4
                    WHEN substr(name_key, 1, length(:needle)) = :needle THEN 5
                    ELSE 6 END,
                    length(name_key), source_file, source_row
                LIMIT :limit
                """,
                {"needle": needle, "limit": limit + 1},
            ).fetchall()
        return [dict(row) for row in rows[:limit]], len(rows) > limit

    def lookup(self, code: str) -> list[dict]:
        key = normalize(code)
        with closing(self.connection()) as db:
            rows = db.execute(
                """
                SELECT source_file, source_row, primary_code, additional_code, name
                FROM diagnoses
                WHERE primary_key = ? OR additional_key = ?
                ORDER BY source_file, source_row
                """,
                (key, key),
            ).fetchall()
        return [dict(row) for row in rows]
