"""Canonical secret-pattern filter for Daniel's GLM/M3 advisory CLIs.
Single source of truth — imported by glm-review and m3-review (use scan()).
Bump FILTER_VERSION on any change; Mac and VPS copies must match (verify via --version).
"""
import re

FILTER_VERSION = "2026-06-28a"

# Literal substrings — distinctive enough that a plain `in` match is safe.
LITERAL_PATTERNS = [
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "SUPABASE_SERVICE_ROLE", "service_role", "DATABASE_URL", "VERCEL_TOKEN",
    "PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "BEGIN OPENSSH PRIVATE KEY",
    "eyJhbGciOi",
]

# Key-like token: `sk-` at a non-word boundary (so risk-based / task-start / ask-mode
# do NOT match), followed by a >=20-char key body (real sk-or-v1-/sk-ant-/sk-proj-/sk-
# keys are far longer; ordinary short kebab tokens stay under the threshold). Hyphens
# allowed inside the body to catch the real `sk-or-v1-<hex>` shape.
KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")

# Kept for --version display / parity reporting (NOT used for matching directly).
SECRET_PATTERNS = LITERAL_PATTERNS + ["sk-or-", "sk-ant-", "sk-proj-", "sk-<key>"]

def scan(text):
    """Return list of matched secret indicators (empty = clean)."""
    hits = [p for p in LITERAL_PATTERNS if p in text]
    if KEY_RE.search(text):
        hits.append("sk-<key>")
    return hits
