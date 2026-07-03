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
| money / auth / migration / deploy / RLS / secrets | L3 | + GLM red-team + GLM audit + M3 audit + **the operator gate** |

## Test gate
- Per-stop `TEST_CMD` (cheap, change-aware): `npx tsc --noEmit`
- Full suite (`npm test`) runs before a PR / in CI — not on every stop.

## Environments (§7a — kills the magic-link / wrong-host pain)
| env | host / URL | DB / project | auth redirect config |
|-----|-----------|--------------|----------------------|
| local | `http://localhost:3000` | ____ | Site URL + redirects MUST include `http://localhost:3000/**` |
| staging | `https://____` | ____ | ____ |
| prod | `https://____` | ____ | ____ |
- **Friction-free local login (no host-swapping):** ____ (redirect allowlist includes localhost · OR dev-login/seed script · OR `generate_link` with `redirect_to=localhost`)

## Test fixtures (deterministic, idempotent seed)
- **Admin:** `____` — role `admin` — seeded by: ____
- **Customer:** `____` — role `customer`, starting balance ____ — seeded by: ____
- Re-check a role **without leaking PII**: `select pu.role from public.users pu join auth.users au on au.id = pu.id where au.email = '<known>'` (role only).

## Sensitive surfaces (fill in)
- e.g. payment/webhook handlers, auth tokens, RLS policies, migrations, deploy config …
