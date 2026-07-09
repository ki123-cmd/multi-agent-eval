"""Build a byte-identical review package from a real public PR.

Every arm of the experiment consumes the exact same package bytes; the sha256 is
recorded alongside each result so that overlap-rate figures can be attributed to
the reviewer rather than to input drift.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

DIFF_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$", re.M)

SCHEMA_PATH = Path(__file__).parent / "schema" / "verdict.schema.json"

# A diff larger than this is skipped outright. We never silently truncate: a
# truncated diff would make "the reviewer missed it" indistinguishable from
# "the reviewer never saw it".
MAX_DIFF_BYTES = 60_000

RUBRIC = """\
You are reviewing a pull request diff. Report only defects you can justify from
the diff itself.

- `critical_issues` are blocking: correctness bugs, crashes, security holes,
  data loss, broken invariants. Style preferences are NOT critical issues.
- `suggestions` are non-blocking and never gate the verdict.
- `verdict` is "FAIL" if and only if `critical_issues` is non-empty.

Do NOT run any commands and do NOT read any files. Everything you need is
inlined below. If you find yourself wanting to inspect the repository, that is a
signal that you should reason from the diff instead.

Before anything else, fill in `canary`:
- `first_changed_file`: the b/ path on the FIRST `diff --git` line, WITHOUT the
  leading `b/`.
- `changed_file_count`: how many `diff --git` lines the diff contains.

Respond with a single JSON object conforming to the schema below, and nothing
else. Use exactly these field names -- inventing your own (`issue`, `location`,
...) makes the verdict unusable.

Codex receives this schema again via `--output-schema`; Claude receives it only
here. Inlining it for both keeps the prompt byte-identical across arms while
narrowing the enforcement gap between them.

## Required JSON schema
```json
{schema}
```
"""


def _rubric() -> str:
    schema = json.dumps(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), indent=2)
    return RUBRIC.replace("{schema}", schema)


@dataclass(frozen=True)
class Package:
    item_id: str
    pr_url: str
    pr_title: str
    prompt: str
    sha256: str
    first_changed_file: str
    changed_file_count: int
    diff_bytes: int

    def to_json(self) -> dict:
        return asdict(self)


class DiffTooLarge(Exception):
    """Raised instead of truncating, so the item is recorded as skipped."""


def fetch_diff(pr_url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(
        pr_url.rstrip("/") + ".diff",
        headers={"User-Agent": "cross-review-harness"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def canary_of(diff: str) -> tuple[str, int]:
    matches = DIFF_HEADER.findall(diff)
    if not matches:
        raise ValueError("diff contains no 'diff --git' header")
    return matches[0][1], len(matches)


def build(item_id: str, pr_url: str, pr_title: str, diff: str) -> Package:
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise DiffTooLarge(f"{item_id}: {len(diff)} bytes > {MAX_DIFF_BYTES}")

    first_file, file_count = canary_of(diff)
    prompt = (
        f"{_rubric()}\n"
        f"## Pull request\n{pr_title}\n\n"
        f"## Diff\n```diff\n{diff}\n```\n"
    )
    return Package(
        item_id=item_id,
        pr_url=pr_url,
        pr_title=pr_title,
        prompt=prompt,
        sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        first_changed_file=first_file,
        changed_file_count=file_count,
        diff_bytes=len(diff.encode("utf-8")),
    )


def write(pkg: Package, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{pkg.item_id}.prompt.txt"
    path.write_text(pkg.prompt, encoding="utf-8")
    return path
