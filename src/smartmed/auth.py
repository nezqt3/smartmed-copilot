"""Local staff credentials and expiring, hashed bearer sessions."""

import argparse
import getpass
import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class LoginThrottled(Exception):
    pass


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS staff (
                    id TEXT PRIMARY KEY, salt BLOB NOT NULL, digest BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    staff_hash TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, staff_id TEXT NOT NULL, expires REAL NOT NULL
                );
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def password_digest(passcode: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", passcode.encode(), salt, 600_000)

    def add_staff(self, staff_id: str, passcode: str):
        if not staff_id.strip() or len(staff_id) > 100 or len(passcode) < 12:
            raise ValueError("Staff ID must be nonblank; passcode needs at least 12 characters")
        salt = secrets.token_bytes(32)
        digest = self.password_digest(passcode, salt)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO staff VALUES (?, ?, ?)", (staff_id, salt, digest))
            db.execute("DELETE FROM sessions WHERE staff_id=?", (staff_id,))

    def login(self, staff_id: str, passcode: str) -> str | None:
        key = hashlib.sha256(staff_id.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE reset_at<=?", (time.time(),))
            row = db.execute("SELECT attempts FROM login_attempts WHERE staff_hash=?", (key,))
            attempts = row.fetchone()
            if attempts and attempts[0] >= 5:
                raise LoginThrottled
            db.execute(
                "INSERT INTO login_attempts VALUES (?, 1, ?) "
                "ON CONFLICT(staff_hash) DO UPDATE SET attempts=attempts+1",
                (key, time.time() + 900),
            )
        with self.connect() as db:
            row = db.execute("SELECT salt, digest FROM staff WHERE id=?", (staff_id,)).fetchone()
            # Perform the same expensive hash for unknown IDs.
            digest = self.password_digest(passcode, row[0] if row else bytes(32))
            if not secrets.compare_digest(digest, row[1] if row else bytes(32)) or row is None:
                return None
            db.execute("DELETE FROM login_attempts WHERE staff_hash=?", (key,))
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode()).hexdigest(), staff_id, time.time() + 3600),
            )
        return token

    def logout(self, token: str):
        with self.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )

    def resolve(self, token: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT staff_id FROM sessions WHERE digest=? AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        return row[0] if row else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staff_id")
    parser.add_argument("--database", type=Path, default=Path("data/staff.sqlite3"))
    args = parser.parse_args()
    passcode = getpass.getpass("Passcode (at least 12 characters): ")
    if passcode != getpass.getpass("Repeat passcode: "):
        parser.error("Passcodes differ")
    AuthStore(args.database).add_staff(args.staff_id, passcode)


if __name__ == "__main__":
    main()
