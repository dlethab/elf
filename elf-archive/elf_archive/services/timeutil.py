from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_iso():
    return datetime.now(timezone.utc).strftime(FMT)


def future_iso(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(FMT)
