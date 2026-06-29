# Project Memory (git-tracked — the portable "Hermes" store)

Durable lessons for this project, loaded at **Session Start** (Operating Contract, step 2).
Unlike machine-local Claude memory, this file **travels with the repo** — every session on
every machine (Mac / VPS) reads it. At the end of a meaningful task, **reflect-and-save**:
append a durable lesson here (a user correction/preference, a non-obvious infra fact not in
code or git, a decision + its reason, or a workflow that will recur) and **commit it**. One
concise entry per item; update an existing entry instead of duplicating; never save noise or
anything already captured in code/git.

## Entries
- **2026-06-29 · Protocol v2.3 is active.** Roster = Claude (build) · Codex (diff gate) · GLM-5.2 full-ZDR (red-team + audit) · M3 `data_collection:deny`, L3-only (optional 2nd auditor; value in divergence) · Daniel (human gate). Full protocol: `docs/MULTI_MODEL_PROTOCOL.md`.
- **Helper CLIs are called by ABSOLUTE path** (Claude Code does not inherit the `~/bin` PATH). Resolve the `glm-*` / `m3-*` paths on first run and record them in the Risk Map.
- **For QA, environment beats code (§7a).** Auth is environment-bound: local dev needs the local origin in the auth redirect allowlist so magic links work without host-swapping; seed a KNOWN admin + customer with documented roles/balances; reading your own DB is PII-bound (select only non-PII columns, e.g. `role`).
- **Two-strikes rule.** If a manual workaround is repeated twice, stop and fix the root cause.
