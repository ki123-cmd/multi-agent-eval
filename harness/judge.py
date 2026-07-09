"""Third-party judge: align free-text findings to the golden comment set.

The judge must not be either model under comparison -- LLM judges favour their
own (and stylistically familiar) generations, so a Claude judge scoring a
Claude-vs-Codex contrast would bias exactly the number we care about.
We use a local model served by ollama.

Residual bias: gpt-oss shares OpenAI lineage with Codex, so it may find Codex's
phrasing more familiar. This is why `run.py` emits a human spot-check sheet and
the report is required to state Cohen's kappa against it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"
JUDGE_MODEL = "gpt-oss:120b-cloud"


class JudgeError(Exception):
    """The judge could not rule. Never degrade this into 'zero matches'."""

SYSTEM = """\
You align code-review findings against a curated golden bug list.

A finding MATCHES a golden comment only if it identifies the SAME underlying
defect. Same file or same general area is NOT enough. Different wording is fine.
Be strict: when unsure, do not match.

Return JSON: {"matches": [{"golden_index": <int>, "finding_index": <int>}]}
Every golden comment matched at most once; every finding used at most once.
Omit golden comments that nothing matched.
"""


def _chat(payload: dict, timeout: int = 300, attempts: int = 4) -> str:
    last = ""
    for i in range(attempts):
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))["message"]["content"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
    raise JudgeError(f"judge unreachable after {attempts} attempts -- {last}")


def match(findings: list[dict], golden: list[dict],
          model: str = JUDGE_MODEL) -> list[tuple[int, int]]:
    """Return [(golden_index, finding_index)] pairs the judge accepted."""
    if not findings or not golden:
        return []

    f_txt = "\n".join(
        f"[{i}] {f.get('title','')} :: {f.get('reason','')}"[:400]
        for i, f in enumerate(findings)
    )
    g_txt = "\n".join(
        f"[{i}] ({g.get('severity','?')}) {g.get('comment','')}"[:400]
        for i, g in enumerate(golden)
    )

    content = _chat({
        "model": model,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",
             "content": f"GOLDEN COMMENTS:\n{g_txt}\n\nFINDINGS:\n{f_txt}"},
        ],
    })

    try:
        raw = json.loads(content).get("matches", [])
    except json.JSONDecodeError as e:
        raise JudgeError(f"judge returned non-JSON: {e}") from e

    seen_g: set[int] = set()
    seen_f: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for m in raw:
        gi, fi = m.get("golden_index"), m.get("finding_index")
        if not isinstance(gi, int) or not isinstance(fi, int):
            continue
        if not (0 <= gi < len(golden) and 0 <= fi < len(findings)):
            continue
        if gi in seen_g or fi in seen_f:
            continue
        seen_g.add(gi)
        seen_f.add(fi)
        pairs.append((gi, fi))
    return pairs
