# Review Ledger — decided findings (false-positive suppression)

Record Codex/GLM/M3 findings you've DECIDED on, so auditors stop re-raising them.
Inject this at session start; auditors MUST check it before raising findings and skip anything here marked `rejected`/`wontfix`.

| date | finding (file:line) | source | verdict | reason |
|------|---------------------|--------|---------|--------|
| 2026-06-28 | _example_ src/foo.ts:42 "unguarded null" | GLM | rejected | guarded by caller; verified by test bar_test.ts |

## Review log (v2.5 — one line per multi-model review; feeds the quarterly right-size read, §10c)

| date | tier | reviewers | raised | verdicts (accepted/rejected/needs-test) |
|------|------|-----------|--------|------------------------------------------|
| 2026-07-02 | _example_ L2 | Codex+GLM | 3 | 1/2/0 |

---

## What a real ledger looks like after a few weeks

Not a template — measured from a **live client project** run under this protocol: a production call platform with billing, auth, a worker, and real customers. Anonymised (no schema, no business logic); the shape is the point.

| | count |
|---|---:|
| Findings the reviewers raised | **18** |
| Did **not** survive verification against the code | **12** |
| Already fixed / won't-fix / a process gate rather than a code bug | **5** |
| Real bugs found that no other reviewer caught | **1** |

**Two-thirds of what the reviewers called P0/P1 was wrong.** Treat that as the normal case rather than a scandal — it is precisely why this protocol refuses to let a model be an authority, and why `file:line` evidence is mandatory. A loop that acts on unverified findings burns your week chasing ghosts, and a reviewer you have learned to ignore is worse than no reviewer at all.

The one that survived is instructive. The **fourth-lineage auditor** — the optional second opinion, the one most often accused of not earning its keep — noticed that a status label mapped one failure reason but not another, so three separate views would show customers and staff the wrong outcome. Tests were green. The other reviewers missed it.

That is the honest trade: **twelve false positives bought one real catch nothing else would have found.** Whether that trade is worth it *on your project* is exactly what this file is for. Log every review. When a reviewer's row shows noise and no unique catches over a real sample, **remove it** — "subtract, don't add" is meant to be a decision backed by this table, not a slogan.
