"""Daily reviewer-call cap — a spend guardrail (R6).

The gate itself is free (local, no model calls); the cost lives in the reviewer
CLIs (glm-*/m3-*) that hit OpenRouter. This counts reviews actually SENT today
(egress-log `phase:"attempt"` entries — REFUSED/too-large/self-test never get
one) across ALL reviewers (they share one egress log), and refuses past a
configurable daily cap, FAIL-CLOSED. So a runaway review loop or many parallel
projects can't silently burn your token budget — the exact pain the field keeps
reporting (and a per-day run cap Iftah Saar described as what lets him sleep).

Wire: call enforce_daily_cap() right before a review is transmitted (after the
secret scan passes, before the send). Configure with COVERLOOP_DAILY_REVIEW_CAP
(default 40); set it to 0 to disable, or raise it for a single run.
"""
import json
import fcntl
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CAP = 40


def _log_path():
    # Same default the reviewer CLIs write to; env-overridable (power users/tests).
    return Path(os.environ.get("COVERLOOP_EGRESS_LOG")
                or (Path.home() / ".config" / "openrouter" / "egress.log"))


def _cap():
    try:
        return int(os.environ.get("COVERLOOP_DAILY_REVIEW_CAP", DEFAULT_CAP))
    except ValueError:
        return DEFAULT_CAP


def sent_today():
    """Number of reviews actually transmitted today (UTC) — counted from the
    egress log's `attempt` markers, which are written only for packets that pass
    the size + secret checks and are about to hit the network."""
    log = _log_path()
    if not log.exists():
        return 0
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # tolerate a partial/corrupt line rather than crash
                if rec.get("phase") == "attempt" and str(rec.get("ts", "")).startswith(day):
                    n += 1
    except OSError:
        # NOT zero. An unreadable quota log used to read as "nothing sent today",
        # which allowed every request precisely when the accounting was broken.
        # A quota that silently stops counting is worse than no quota, because the
        # operator still believes there is a ceiling. Raise and let the caller
        # fail closed.
        raise
    return n


def enforce_daily_cap():
    """Fail closed (exit 4) if today's sent reviews have reached the cap. A no-op
    when the cap is <= 0 (disabled) or when the count is safely under it."""
    cap = _cap()
    if cap <= 0:
        return
    try:
        used = sent_today()
    except OSError as exc:
        print(f"egress cap: cannot read the quota log ({exc}); refusing to send. "
              f"Fix the log at {_log_path()} or set COVERLOOP_DAILY_REVIEW_CAP=0 "
              f"to disable the cap deliberately.", file=sys.stderr)
        sys.exit(4)
    if used >= cap:
        sys.stderr.write(
            "coverloop: daily review cap reached (%d/%d reviews sent today). Refusing to send "
            "more — this protects your token budget across parallel projects. Raise it for this "
            "run with COVERLOOP_DAILY_REVIEW_CAP=%d, or set it to 0 to disable.\n"
            % (used, cap, cap * 2))
        sys.exit(4)


def reserve_daily_slot(record_attempt):
    """Count today's sends and record this one as a SINGLE atomic step.

    `enforce_daily_cap()` only counts. The caller then records its attempt a few
    lines later, and in that gap two reviewers running against different projects
    could both read cap-1, both pass, and both send — so the documented
    parallel-project protection did not hold. Holding an exclusive lock across
    check-and-record closes the window: at most `cap` processes can observe a
    count below the cap.

    Falls back to the old check-then-record if the filesystem cannot lock, and
    SAYS SO rather than pretending. This is a spend guardrail, not a safety
    boundary; refusing to run at all on an exotic filesystem would be friction
    with no security to show for it.
    """
    cap = _cap()
    if cap <= 0:
        record_attempt()
        return
    log = _log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(log) + ".lock"
        with open(lock_path, "a+") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                _check_and_record(cap, record_attempt)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        return
    except OSError as exc:
        print(f"egress cap: proceeding without a lock ({exc}); the daily cap is "
              f"still enforced but is not safe against reviewers running in "
              f"parallel.", file=sys.stderr)
    _check_and_record(cap, record_attempt)


def _check_and_record(cap, record_attempt):
    try:
        used = sent_today()
    except OSError as exc:
        print(f"egress cap: cannot read the quota log ({exc}); refusing to send.",
              file=sys.stderr)
        sys.exit(4)
    if used >= cap:
        print(f"egress cap: {used}/{cap} reviews already sent today; refusing. "
              f"Raise COVERLOOP_DAILY_REVIEW_CAP or wait for the UTC day to roll.",
              file=sys.stderr)
        sys.exit(4)
    record_attempt()
