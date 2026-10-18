#!/usr/bin/env python3
"""Local failure metadata: never retain commands, errors, output or supplied paths."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

MAX_INPUT = 65536
MAX_LOG = 262144
KEEP = 300
EVENTS = {"PostToolUseFailure", "Stop"}
TOOLS = {"Bash", "Read", "Write", "Edit", "MultiEdit", "Grep", "Glob", "WebFetch", "WebSearch", "Task"}


def summarize(raw):
    record = {"schema": "coverloop-failure/v1", "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "event": "unknown", "tool": "other", "exit_code": None,
              "input": "invalid-json", "fingerprint": hashlib.sha256(raw).hexdigest()}
    if len(raw) > MAX_INPUT:
        record["input"] = "oversized-prefix"
        return record
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return record
    if not isinstance(event, dict):
        return record
    record["input"] = "json"
    if isinstance(event.get("hook_event_name"), str) and event["hook_event_name"] in EVENTS:
        record["event"] = event["hook_event_name"]
    if isinstance(event.get("tool_name"), str) and event["tool_name"] in TOOLS:
        record["tool"] = event["tool_name"]
    code = event.get("exit_code")
    if type(code) is int and -255 <= code <= 255:
        record["exit_code"] = code
    return record


def project_id():
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / ".git").exists():
            return hashlib.sha256(os.fsencode(str(p))).hexdigest()[:24]
    return None


def directory(parent, name, private=False):
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    st = os.fstat(fd)
    if st.st_uid != os.getuid() or st.st_mode & (0o077 if private else 0o022):
        os.close(fd)
        raise ValueError("unsafe directory")
    return fd


def regular(parent, name):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
        os.close(fd)
        raise ValueError("unsafe file")
    return fd


def valid(item, record):
    try:
        return (set(item) == set(record) and item["schema"] == record["schema"]
            and isinstance(item["event"], str) and item["event"] in EVENTS | {"unknown"}
            and isinstance(item["tool"], str) and item["tool"] in TOOLS | {"other"}
            and (item["exit_code"] is None or type(item["exit_code"]) is int and -255 <= item["exit_code"] <= 255)
            and item["input"] in ("json", "invalid-json", "oversized-prefix")
            and isinstance(item["fingerprint"], str) and len(item["fingerprint"]) == 64
            and all(c in "0123456789abcdef" for c in item["fingerprint"])
            and isinstance(item["time"], str) and len(item["time"]) <= 40
            and datetime.datetime.fromisoformat(item["time"]).tzinfo is not None)
    except (ValueError, TypeError, KeyError):
        return False


def append(record, namespace):
    opened = []
    try:
        home = os.open(str(Path.home()), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(home)
        claude = directory(home, ".claude")
        opened.append(claude)
        folder = directory(claude, "coverloop-failures", private=True)
        opened.append(folder)
        lock = regular(folder, namespace + ".lock")
        opened.append(lock)
        # Contention drops an event with a diagnostic; never hangs an agent.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = regular(folder, namespace + ".jsonl")
        opened.append(fd)
        if os.fstat(fd).st_size > MAX_LOG:
            raise ValueError("oversized log")
        old = os.read(fd, MAX_LOG + 1).splitlines()
        safe = []
        for line in old:
            try:
                item = json.loads(line)
                if valid(item, record):
                    safe.append(json.dumps(item, separators=(",", ":")))
            except (ValueError, TypeError, RecursionError):
                continue
        safe = safe[-(KEEP - 1):] + [json.dumps(record, separators=(",", ":"))]
        data = ("\n".join(safe) + "\n").encode()
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def main():
    try:
        namespace = project_id()
        if namespace is None:
            return 0
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        append(summarize(raw), namespace)
    except Exception:
        print("coverloop: failure metadata not saved; check local log permissions or lock contention.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
