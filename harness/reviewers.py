"""Symmetric adapters for the Claude and Codex reviewers.

Symmetry is what makes the comparison valid: both reviewers see byte-identical
input, neither has tools, and both are asked for the same schema. The one
asymmetry we cannot remove -- Codex enforces the schema with `--output-schema`,
`claude -p` does not -- is measured rather than hidden (see `schema_failure`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema" / "verdict.schema.json"


def resolve(exe: str) -> str:
    """On Windows these CLIs are npm .cmd shims; CreateProcess needs the full path."""
    path = shutil.which(exe)
    if not path:
        # Never fall back to another model to stand in for a missing backend --
        # that is how you end up believing you ran a cross-model experiment.
        raise FileNotFoundError(f"{exe} not on PATH; refusing to substitute a backend")
    return path

# Codex can only read files here with the sandbox disabled (verified: read-only
# and workspace-write both die with CreateProcessWithLogonW 1385). A reviewer
# that can write the workspace is not a reviewer, so these modes are banned.
BANNED_SANDBOX = {"danger-full-access", "workspace-write"}

NO_TOOLS = "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch,Task,NotebookEdit"


@dataclass
class RunResult:
    backend: str
    model: str
    effort: str
    argv: list[str]
    raw: str
    verdict: dict | None
    duration_ms: int
    cost_usd: float | None = None
    tokens: dict = field(default_factory=dict)
    schema_failure: bool = False
    error: str | None = None


def _first_json(text: str) -> dict | None:
    """Extract the first JSON object. Tolerates fences and trailing NDJSON."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def review_codex(prompt: str, model: str, effort: str, workdir: Path,
                 sandbox: str = "read-only", timeout: int = 900) -> RunResult:
    if sandbox in BANNED_SANDBOX:
        raise ValueError(f"sandbox={sandbox} would let the reviewer touch the repo")

    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "codex_last.json"
    argv = [
        resolve("codex"), "exec",
        "--sandbox", sandbox,
        "--skip-git-repo-check",
        "--ephemeral",
        "-m", model,
        "-c", f"model_reasoning_effort={effort}",
        "--output-schema", str(SCHEMA_PATH),
        "-o", str(out),
        "-",
    ]
    t0 = time.time()
    proc = subprocess.run(argv, input=prompt, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=workdir)
    dt = int((time.time() - t0) * 1000)

    raw = out.read_text(encoding="utf-8", errors="replace") if out.exists() else proc.stdout
    verdict = _first_json(raw)

    # The 1385 sandbox failure exits 0 with a schema-valid body. Surface it.
    sandbox_broke = "CreateProcessWithLogonW" in (proc.stderr or "") or \
                    "windows sandbox" in (proc.stderr or "")

    return RunResult(
        backend="codex", model=model, effort=effort, argv=argv, raw=raw,
        verdict=verdict, duration_ms=dt, schema_failure=verdict is None,
        error="codex sandbox exec failure (tool calls blocked)" if sandbox_broke else None,
    )


def review_claude(prompt: str, model: str, effort: str, workdir: Path,
                  timeout: int = 900) -> RunResult:
    workdir.mkdir(parents=True, exist_ok=True)
    argv = [
        resolve("claude"), "-p",
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", NO_TOOLS,
        "--max-turns", "1",
    ]
    t0 = time.time()
    proc = subprocess.run(argv, input=prompt, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=workdir)
    dt = int((time.time() - t0) * 1000)

    envelope = _first_json(proc.stdout) or {}
    inner = envelope.get("result", "")
    verdict = _first_json(inner) if isinstance(inner, str) else None
    usage = envelope.get("usage") or {}

    return RunResult(
        backend="claude", model=model, effort=effort, argv=argv, raw=proc.stdout,
        verdict=verdict, duration_ms=dt,
        cost_usd=envelope.get("total_cost_usd"),
        tokens={k: usage.get(k) for k in
                ("input_tokens", "output_tokens", "cache_creation_input_tokens")},
        schema_failure=verdict is None,
        error=None if envelope else "claude returned no JSON envelope",
    )
