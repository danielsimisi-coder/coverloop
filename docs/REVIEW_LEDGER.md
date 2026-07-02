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
