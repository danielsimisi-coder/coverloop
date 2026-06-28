# Risk Map — <PROJECT>

Per-project control sheet for the v2.3 loop. Fill on first run; keep it current.
(If you maintain this in Obsidian instead, delete this file and keep the canonical map there.)

## Helper absolute paths
Claude Code does NOT inherit your terminal `~/bin` PATH — record the resolved absolute paths and always call helpers by them.
- `glm-review`: `/ABS/PATH/glm-review`
- `glm-audit` : `/ABS/PATH/glm-audit`
- `m3-review` : `/ABS/PATH/m3-review`   (or **PARKED** on this machine)

## Privacy posture (verify, don't assume — re-check when reusing later)
- **GLM** full-ZDR via Z.AI — `glm-audit --zdr-selftest` → OK on: ____
- **M3** `data_collection:deny` (no-training, **NOT** full ZDR) — `m3-review --privacy-selftest` → OK on: ____  | or **PARKED**
- **Never send:** `.env`, secrets, keys, tokens, whole-repo dumps, customer data.

## Risk tiers for THIS project (edit the examples)
| Area | Tier | Gate |
|------|------|------|
| copy / comments / CSS polish | L0 | quick check |
| isolated component / small bug fix | L1 | relevant tests + typecheck |
| product flow (no money/auth/migration) | L2 | + Codex **mandatory** |
| money / auth / migration / deploy / RLS / secrets | L3 | + GLM red-team + GLM audit + M3 audit + **Daniel gate** |

## Test gate
- Per-stop `TEST_CMD` (cheap, change-aware): `npx tsc --noEmit`
- Full suite (`npm test`) runs before a PR / in CI — not on every stop.

## Sensitive surfaces (fill in)
- e.g. payment/webhook handlers, auth tokens, RLS policies, migrations, deploy config …
