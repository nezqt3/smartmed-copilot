"""Prevent multiple local API workers from resetting each other's persisted jobs."""
import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def worker_lease(database: Path):
    # Keep the inode after releasing the lock: unlinking could permit two leases.
    with database.with_name(database.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This database already has an API worker; use --workers 1") from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
