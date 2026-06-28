---
name: reflect-and-save
description: At the end of a meaningful task, reflect on what was learned and save durable lessons to memory (the self-improving loop / "periodic nudge"). Use after finishing a non-trivial task, a fix, a decision, or when the user gives feedback worth keeping. Skip on trivial/conversational turns.
---

# Reflect & save (self-improving loop)

After a meaningful task, reflect and persist what's durable. The model isn't retrained — it keeps better notes.

## Steps
1. Ask: did anything happen worth remembering next session?
   - user correction/preference (how they want you to work) -> type: feedback
   - non-obvious project/infra fact NOT in code or git -> type: project
   - a decision + its reason -> type: project
   - pointer to an external resource -> type: reference
   - who the user is -> type: user
2. If NOTHING durable -> say so and stop. Don't save noise or facts the repo/git already record.
3. If yes -> write ONE memory file per fact (frontmatter: name, description, metadata.type), update the MEMORY.md index. Check for an existing file first -> update, don't duplicate. Link related memories with [[name]].
4. If a workflow recurred, capture it as a new Skill instead of a memory.
5. Keep entries compact.

## When to skip
Trivial edits, pure conversation, or anything already captured.

## v2.3 additions
- First check `~/.claude/reflect-staging.md` (auto-captured failures) and curate anything durable from it.
- PROVENANCE GUARD: never paste GLM/M3/Codex text verbatim into memory — rewrite the lesson in your own words, human-confirmed.
- Prefer rewriting an existing memory/lesson over appending a near-duplicate (avoid bloat).
