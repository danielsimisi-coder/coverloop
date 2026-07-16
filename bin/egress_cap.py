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
        return 0
    return n


def enforce_daily_cap():
    """Fail closed (exit 4) if today's sent reviews have reached the cap. A no-op
    when the cap is <= 0 (disabled) or when the count is safely under it."""
    cap = _cap()
    if cap <= 0:
        return
    used = sent_today()
    if used >= cap:
        sys.stderr.write(
            "coverloop: daily review cap reached (%d/%d reviews sent today). Refusing to send "
            "more — this protects your token budget across parallel projects. Raise it for this "
            "run with COVERLOOP_DAILY_REVIEW_CAP=%d, or set it to 0 to disable.\n"
            % (used, cap, cap * 2))
        sys.exit(4)
