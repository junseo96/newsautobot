"""One-time, recoverable reset of unprocessed V11 news candidates.

Run only while the Newsflow-V11-Continuous scheduled task is stopped. This
script never touches the delivery database, Gmail state, receipts, or ACKs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid

from v11_runtime import InstanceLock, Queue, stamp


PENDING = ("queued", "deferred", "inflight", "ready_day")


def reset(root: Path, max_age_hours: int = 12) -> dict:
    root = root.resolve()
    work = root / "work" / "v11"
    database = work / "queue.db"
    if not database.is_file():
        raise FileNotFoundError(f"Existing V11 queue is required: {database}")
    if not 1 <= max_age_hours <= 24:
        raise ValueError("Realtime candidate age must be between 1 and 24 hours")
    with InstanceLock(work / "supervisor.lock"):
        archive_dir = work / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / ("queue-before-realtime-reset-" +
            dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8] + ".db")
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(archive)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Queue backup did not pass SQLite integrity check")
        queue = Queue(database)
        cutoff = dt.datetime.now(dt.timezone.utc).timestamp()
        with queue.connect() as con:
            before = dict(con.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
            removed = con.execute("DELETE FROM jobs WHERE status IN (?,?,?,?)", PENDING).rowcount
            queue._set(con, "realtime_start_epoch", cutoff)
            queue._set(con, "realtime_max_age_hours", max_age_hours)
            queue._set(con, "last_queue_reset", {"at": stamp(), "archive": str(archive),
                "removed": removed, "statuses": list(PENDING), "max_age_hours": max_age_hours})
            con.execute("INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)",
                (stamp(), None, "realtime_reset", f"Removed {removed} unprocessed jobs; backup {archive.name}"))
        after = queue.counts()
        if any(after.get(status, 0) for status in PENDING):
            raise ValueError("An unprocessed queue status remained after reset")
        if after.get("delivered", 0) != before.get("delivered", 0) or after.get("reviewed", 0) != before.get("reviewed", 0):
            raise ValueError("Completed queue records changed during reset")
        return {"archive": str(archive), "removed": removed, "before": before,
                "after": after, "realtime_start_utc": dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).isoformat(),
                "max_candidate_age_hours": max_age_hours}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--max-age-hours", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(reset(args.root, args.max_age_hours), ensure_ascii=False))
