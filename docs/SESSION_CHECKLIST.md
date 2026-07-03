# the operator's Session Checklist — the human routine

What **you** do around every session. Two prompts to open, three things to watch, three to close.

---

## Once per project (set up once, then forget)
So sessions auto-load the protocol instead of you reminding them:
- [ ] **Machine:** `cd <protocol-repo> && ./install.sh` — CLIs + hooks, auto-wired.
- [ ] **Project:** run `<protocol-repo>/init-project.sh` in the repo root — creates `loop.conf`, `docs/MEMORY.md`, `RISK_MAP.md`, `OPERATING_CONTRACT.md` (new files only).
- [ ] **The one edit that makes it stick:** inline `docs/OPERATING_CONTRACT.md` at the **top of that project's `CLAUDE.md`**. This is what survives compaction — without it, long sessions forget the protocol.

---

## EVERY new session — 3 steps (~30 seconds)

**1. Paste Session-Start** (makes it load the protocol + memory):
```
Session Start (v2.4). Before any work, do this and report:
1. State PROTOCOL_VERSION + the 5-role roster (Claude build · Codex diff-gate · GLM full-ZDR red-team/audit · M3 L3-only 2nd auditor · the operator gate).
2. Read docs/MEMORY.md and summarize what's relevant to today.
3. Read the Risk Map + docs/REVIEW_LEDGER.md (skip already-rejected findings).
4. Resolve the absolute paths of glm-*/m3-* and record them in the Risk Map.
5. Restate today's Task + risk tier (L0–L3) before touching code.
If the Operating Contract is NOT in your loaded CLAUDE.md, say so — that's a wiring bug.
```

**2. Paste the wiring check** (5-second proof it's actually loaded):
```
From your loaded context only (don't open files): (a) what PROTOCOL_VERSION? (b) name the 5 roster members. (c) where is durable memory stored? If you can't answer (a)+(b) from loaded context, the protocol isn't wired — stop and flag it.
```
> If it can't answer → the contract isn't inlined in CLAUDE.md. Fix the wiring before real work.

**3. Give it the task** — and require it to name the **risk tier (L0–L3)** before touching code.

---

## DURING the session — watch for 3 things
- **Drift** → if it acts without naming the tier, or skips Codex on L2 / GLM on L3: say **"what risk tier is this, and which gates apply?"** (or just re-paste Session-Start — it reloads everything in 5s).
- **Gates** → before any **push / merge / migration / deploy** it must show you the gate. **You approve every L3.** Nothing risky ships without your explicit OK.
- **Task pileup** → if background tasks stack up: **"reap finished background jobs; keep at most one dev server."**

---

## CLOSING a session (before you stop or walk away)
- [ ] **"Run reflect-and-save"** → commit durable lessons to `docs/MEMORY.md` (so the next session inherits them).
- [ ] **"Reap background tasks"** → confirm nothing's left running.
- [ ] **"Final Report"** → what's *merged* vs *deployed* vs *pending a gate* (never let "merged" read as "live").

---

## 3 golden rules
1. **Restart long sessions.** Don't let one run 15–20h — it drifts and piles up tasks. Finish a chunk, close it out, start fresh; a new session reloads the protocol clean.
2. **You are the gate.** No merge / deploy / migration / secret without your explicit approval.
3. **When in doubt, re-paste Session-Start.** It re-loads the whole protocol in 5 seconds — cheaper than debugging a drifted session.
