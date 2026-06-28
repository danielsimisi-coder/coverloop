# Review Ledger — decided findings (false-positive suppression)

Record Codex/GLM/M3 findings you've DECIDED on, so auditors stop re-raising them.
Inject this at session start; auditors MUST check it before raising findings and skip anything here marked `rejected`/`wontfix`.

| date | finding (file:line) | source | verdict | reason |
|------|---------------------|--------|---------|--------|
| 2026-06-28 | _example_ src/foo.ts:42 "unguarded null" | GLM | rejected | guarded by caller; verified by test bar_test.ts |
