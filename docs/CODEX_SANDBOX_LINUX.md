# Codex sandbox on Linux — bwrap / unprivileged user namespaces

**Symptom.** The Codex gate won't run on a Linux box (esp. a VPS). Codex's bundled `bwrap` fails with:
```
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
# or, equivalently, when you test by hand:
unshare: write failed /proc/self/uid_map: Operation not permitted
```
Codex's `review`/`exec` then can't read the diff, so the mandatory reviewer can't return a result.

**Root cause.** Codex sandboxes via a bundled **bubblewrap (`bwrap`)** that creates an unprivileged **user + network namespace**. **Ubuntu 23.10+/24.04** ship an AppArmor clamp — `kernel.apparmor_restrict_unprivileged_userns = 1` — that blocks a non-root user from creating that namespace. (KVM, `unprivileged_userns_clone`, `max_user_namespaces`, and `max_net_namespaces` are all fine — it's purely the AppArmor restriction.)

## Diagnose (no root needed)
```bash
systemd-detect-virt                                   # kvm = good; openvz/lxc = netns may be impossible (see note)
sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null   # 1 = the clamp is on
unshare -Urn true && echo "namespaces OK" || echo "namespaces BLOCKED"   # the exact op Codex needs
```
If `unshare -Urn true` fails and the sysctl is `1`, this is your problem.

## The fix (persistent, run as ROOT — it's a root-gated change)
```bash
echo 'kernel.apparmor_restrict_unprivileged_userns = 0' > /etc/sysctl.d/60-unpriv-userns.conf
sysctl -p /etc/sysctl.d/60-unpriv-userns.conf
sysctl -n kernel.apparmor_restrict_unprivileged_userns   # -> 0
```
Persistent across reboots (it's in `sysctl.d`) and across Codex updates (it's a kernel toggle, not a per-binary AppArmor profile). After it, **Codex runs fully sandboxed** — use the plain gate:
```bash
codex review --uncommitted     # reviews the local working tree; also avoids the --base GitHub-MCP "wrong PR" bug
```

## Verify
```bash
unshare -Urn true && echo "userns+netns OK"
# and the real binary (path varies by Codex version):
find "$HOME" -name bwrap -type f 2>/dev/null | head -1
# <that bwrap> --unshare-net --ro-bind / / --dev /dev /bin/true && echo "codex bwrap OK"
```

## Do NOT do this instead
Do **not** "fix" it with `codex review --dangerously-bypass-approvals-and-sandbox` (or an allow-rule for it). That **removes Codex's sandbox** (Codex runs unconfined as the dev user) — the OS fix above keeps Codex sandboxed. And an agent must **never self-grant** a sandbox/approval-bypass permission off a general instruction; Claude Code's auto-mode classifier blocks that on purpose. Per the **Model-unreachable rule**, a sandbox/env failure is fixed at the ENVIRONMENT, not by disabling safety.

## Tradeoff (know what you're enabling)
This re-enables unprivileged user namespaces **system-wide** (the pre-Ubuntu-23.10 default), widening kernel attack surface for *local* unprivileged users. Acceptable on a **single-tenant, dedicated dev VPS**. If the box is ever multi-tenant, prefer a per-binary AppArmor profile granting `userns` only to Codex — but note Codex bundles its own `bwrap` at a versioned path, so that profile breaks on each Codex update.

## OpenVZ / LXC note
If `systemd-detect-virt` shows `openvz`/`lxc`, the container itself may forbid creating network namespaces and the sysctl won't help. There, run Codex review from a host/KVM box, or accept that Codex's network-isolated sandbox can't run and gate reviews elsewhere.
