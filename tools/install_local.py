#!/usr/bin/env python3
"""Explicit, offline installer for the existing engine and Claude Code hooks."""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent.parent


def check_path(path, home):
    if ".." in path.parts or not path.is_absolute() or not path.is_relative_to(home):
        raise ValueError("destination must be inside the user's home directory")
    current = home
    for part in ("", *path.relative_to(home).parts):
        if part:
            current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise ValueError("destination is symlinked, not owned, or writable by other users")
        if not stat.S_ISDIR(st.st_mode) and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1):
            raise ValueError("destination is not a private regular file/directory")


def files(home, bin_dir):
    result = {}
    for p in (ROOT / "bin").iterdir():
        if p.is_file() and not p.is_symlink():
            result[bin_dir / p.name] = (p.read_bytes(), 0o700)
    for p in (ROOT / "hooks").iterdir():
        if p.suffix in (".py", ".sh") and p.is_file() and not p.is_symlink():
            result[home / ".claude" / "hooks" / p.name] = (p.read_bytes(), 0o700)
    for p in (ROOT / "skills").glob("*/SKILL.md"):
        result[home / ".claude" / "skills" / p.parent.name / "SKILL.md"] = (p.read_bytes(), 0o600)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="approve copying the displayed files")
    p.add_argument("--wire-hooks", action="store_true", help="also approve merging Claude Code user hook settings")
    p.add_argument("--replace-existing", action="store_true", help="approve replacing different files, with backups")
    p.add_argument("--bin-dir", help="custom absolute helper directory inside your home (also honors BIN_DIR)")
    args = p.parse_args()
    home = Path.home().absolute()
    try:
        bin_dir = Path(args.bin_dir or os.environ.get("BIN_DIR") or str(home / "bin"))
        check_path(bin_dir, home)
        targets = files(home, bin_dir)
        if args.wire_hooks:
            settings = home / ".claude" / "settings.json"
            check_path(settings, home)
            config = json.loads(settings.read_text()) if settings.exists() else {}
            if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
                raise ValueError("invalid settings object")
            hooks = config.setdefault("hooks", {})
            for event, name, matcher in (("SessionStart", "session-contract.sh", None),
                                          ("PreToolUse", "pre-risky-git.sh", "Bash"),
                                          ("Stop", "loop-stop-check.sh", None),
                                          ("PostToolUseFailure", "capture-failure.sh", None)):
                arr = hooks.setdefault(event, [])
                if not isinstance(arr, list):
                    raise ValueError("invalid hook settings")
                command = shlex.quote(str(home / ".claude" / "hooks" / name))
                wired = any(isinstance(e, dict) and (matcher is None or e.get("matcher") == matcher)
                            and isinstance(e.get("hooks", []), list)
                            and any(isinstance(h, dict) and h.get("command") in (command, str(home / ".claude" / "hooks" / name))
                                    for h in e.get("hooks", [])) for e in arr)
                if not wired:
                    entry = {"hooks": [{"type": "command", "command": command}]}
                    if matcher:
                        entry["matcher"] = matcher
                    arr.append(entry)
            targets[settings] = ((json.dumps(config, indent=2) + "\n").encode(), 0o600)
        changes = []
        for path, (data, mode) in targets.items():
            check_path(path, home)
            if path.exists() and path.is_dir():
                raise ValueError("file destination is a directory")
            if not path.exists() or path.read_bytes() != data or stat.S_IMODE(path.stat().st_mode) != mode:
                changes.append((path, data, mode))
        replacing = [str(path.relative_to(home)) for path, _, _ in changes if path.exists()]
        # Print only our own paths and static metadata, never settings content.
        print(json.dumps({"mode": "apply" if args.apply else "plan", "home": str(home),
                          "files": [str(path.relative_to(home)) for path, _, _ in changes],
                          "replacing": replacing, "wire_hooks": args.wire_hooks,
                          "network_calls": 0, "reads_credentials": False,
                          "system_packages_installed": 0}, indent=2))
        if not args.apply:
            return 0
        if replacing and not args.replace_existing:
            raise ValueError("existing files differ; inspect plan and authorize --replace-existing")
        for path, data, mode in changes:
            check_path(path, home)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            check_path(path, home)
            if path.exists():
                backup = path.with_name(path.name + ".coverloop-backup-" + uuid.uuid4().hex)
                with open(backup, "xb") as f:
                    os.fchmod(f.fileno(), 0o600)
                    f.write(path.read_bytes())
            fd, temporary = tempfile.mkstemp(prefix=".coverloop-install-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    os.fchmod(f.fileno(), mode)
                    f.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        print("Installed offline. No credentials read, no model calls, no projects trusted.")
        print("Next: inspect project test commands, then run init-project.sh; trust requires --trust.")
        return 0
    except (OSError, ValueError, TypeError):
        print("Installation refused: unsafe destination, invalid settings, or unapproved replacement. No automatic fallback. Inspect the plan and local permissions.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
