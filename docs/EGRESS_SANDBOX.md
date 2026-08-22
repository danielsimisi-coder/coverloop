# Egress allowlist + OS sandbox (optional, root-gated defense-in-depth)

This is the one v2.3 tripwire the install scripts **cannot** apply for you: it needs root and is
machine-specific, so getting it wrong can lock the box out of the network. Treat it as **belt-and-
suspenders**, not a prerequisite — the core privacy controls already run at the tool layer (`redact()`
on every packet before egress; its documented residual false-negatives are in `CHANGELOG.md`).

## What already protects you (no root needed — shipped by install.sh)
- The worker runs as a **non-root user** (e.g. `your-vps-user` / `your-vps-user`), not root.
- `glm_secret_filter.py` **refuses** to send `.env`/keys/tokens/DB URLs (boundary-aware, fail-closed).
- Provider routing is pinned: GLM `{zdr:true, allow_fallbacks:false, data_collection:deny}`, M3
  `{data_collection:deny, allow_fallbacks:false}`. Self-test with `--zdr-selftest` / `--privacy-selftest`.
- Append-only **egress log** records a `sha256` of every payload (never the body) for audit.

So the model helpers already only talk to OpenRouter, only after the secret scan, and never train on data.

## Optional extra: outbound allowlist (run as root, on YOUR gate)
Restrict the worker user's outbound traffic to the few hosts the loop needs. **Keep a second root
console open before you apply this — a wrong rule can cut your SSH.** Example with `ufw` (adapt to
your distro/firewall, and resolve current IPs/CIDRs — these change):

```bash
# ALLOW the essentials, then default-deny egress. REVIEW every line first.
#   - openrouter.ai            (the only model endpoint)
#   - github.com / api.github  (gh + git)
#   - registry.npmjs.org       (npm) — if the box builds
#   - your DB / deploy host     (Supabase / Vercel) as needed
# ufw is host-based; for IP pinning use iptables/nftables with the resolved CIDRs.
sudo ufw default deny outgoing
sudo ufw default deny incoming
sudo ufw allow out 53           # DNS
sudo ufw allow out to any port 443 proto tcp   # start broad on 443, then tighten to specific hosts
sudo ufw allow out 22           # git/ssh if needed
sudo ufw enable
```

Tighten the broad `443` rule to specific destination IPs once you've confirmed the loop works, using
`iptables`/`nftables` with the resolved CIDRs for the hosts above. Verify the helpers still pass their
self-tests afterward (`glm-audit --zdr-selftest`, `m3-review --privacy-selftest`).

## OS sandbox (alternative / addition)
On the Mac, Claude Code's own `settings.json` permission rules already deny reads of `.ssh/.env/keys/
keychains` and gate `curl/ssh/scp/rm -rf/sudo`. On Linux you can additionally run the worker under
`systemd` hardening (`ProtectHome`, `ReadOnlyPaths`, `IPAddressAllow=`) or a container — same goal:
the worker user can only reach what the loop needs.
