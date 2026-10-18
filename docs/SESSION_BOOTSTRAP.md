# Session bootstrap — Coverloop 2.12.4 candidate

## Machine

Use macOS or Linux, Python 3.9+, Bash and Git. Claude Code drives the workflow;
Codex CLI with a working buyer-owned account is needed for L2/L3 independent review.
OpenRouter is separate and buyer-funded for advisory plan review. No provider usage
is included in the MIT engine or a commercial onboarding package.

The public repository can be cloned without signing in. For reproducible installation,
use an approved full commit SHA, not `main`. Inspect the checkout before execution.

```bash
./install.sh                       # offline preview; changes nothing
./install.sh --apply               # approve listed file copies
./install.sh --wire-hooks          # preview optional user hook settings
# After inspecting that plan, run in your terminal:
./install.sh --apply --wire-hooks
```

A changed existing file or file mode needs `--replace-existing`; private backups are
kept alongside replaced files. Custom `BIN_DIR` / `--bin-dir` is supported inside
owned, non-symlinked home directories. For other locations, use the inspected source
checkout directly. No automatic shell-profile changes or system packages are installed.
Do not bypass a host rule that prevents agents changing their own hook settings.

Run `~/bin/coverloop doctor --no-credentials` first. It inventories local tools and
reports unavailable reviewers without reading keys or making network calls. The normal
`doctor` inspects credential availability; `protocol-selftest` can make paid provider
calls. Authorize those separately. Configure keys privately using your provider's
supported method; never paste them into chat, commit them, or include them in logs.
Linux sandbox setup is a separate check; do not disable it or automatically weaken
system-wide security settings.

## Project

Inspect the actual repository and its test command before trusting it:

```bash
cd /absolute/path/to/project
/path/to/coverloop/init-project.sh   # generic templates; no automatic trust
/path/to/coverloop/bin/coverloop init --test-command 'YOUR_REVIEWED_TEST_COMMAND'
```

Replace the example command with an installed, project-appropriate test runner.
The default is `false`, so an unconfigured project cannot accidentally pass. Avoid
package-manager commands that download or install dependencies implicitly.
Configure `.claude/loop.conf` independently for the cheap Stop-hook check.
`init-project.sh` preserves existing project files and never imports this repository's
review history. It may append the required local-counter gitignore entry.

With project-owner permission, inline `docs/OPERATING_CONTRACT.md` in `CLAUDE.md`.
After inspecting the test command, explicitly run `init-project.sh --trust` to allow
this project's Stop hook. Hooks provide context and a bounded completion check;
only `coverloop gate` enforces evidence requirements. Use a required CI check for
repository enforcement. GitHub branch rules/settings need separate authorization.

## Session and evidence

1. Read the project's contract, risk map and relevant approved memory; do not ingest
   legacy raw failure logs. Resolve engine path/version and report missing dependencies.
2. Classify the actual diff, using a trusted base. Raise the tier if semantics warrant it.
3. Build and test. At L3, run real guard-break experiments before independent diff review.
4. Obtain genuine Codex review for L2+. An unavailable or failed reviewer cannot pass.
   Advisory Kimi plan review uses `glm-*`; optional M3 needs its own privacy opt-in.
5. Record only actual evidence with `attest`. Commit the evidence files, then verify
   at the final HEAD with `gate --require-transcript` and the derived tier floor.
6. L3 also requires a named human approval. Never record it without actual permission.
   Passing the gate does not authorize push, merge, deployment, billing or production work.

Keep durable, approved project lessons in `docs/MEMORY.md`. The new failure hook keeps
only bounded diagnostic metadata under the current project's hashed namespace. Old
`reflect-staging.md` files are not read or migrated; the owner can inspect them privately.
