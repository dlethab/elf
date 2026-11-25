import time


def _now():
    return int(time.time())


def count(db, bucket, window):
    return db.execute("SELECT COUNT(*) FROM rate_events WHERE bucket=? AND at>?",
                      (bucket, _now() - window)).fetchone()[0]


def hit(db, bucket):
    db.execute("INSERT INTO rate_events(bucket, at) VALUES (?,?)", (bucket, _now()))


def allow(db, bucket, limit, window):
    """Record an attempt; False when the bucket is already at its limit."""
    if count(db, bucket, window) >= limit:
        return False
    hit(db, bucket)
    return True


def prune(db, older_than=86400):
    db.execute("DELETE FROM rate_events WHERE at<?", (_now() - older_than,))
