"""Turn silent failure into hard failure.

The motivating observation: on this machine Codex's sandbox blocks its file
reads, yet it still exits 0 and returns a schema-valid `FAIL` verdict. Exit code
and schema conformance are therefore both useless as liveness signals. The
canary is not.
"""
from __future__ import annotations

from dataclasses import dataclass

VALID = "VALID"
INVALID = "INVALID"

_SEVERITIES = {"low", "medium", "high", "critical"}
_CONFIDENCE = {"low", "medium", "high"}


@dataclass
class Validation:
    status: str
    reasons: list[str]

    @property
    def ok(self) -> bool:
        return self.status == VALID


def _shape_errors(v: dict) -> list[str]:
    errs: list[str] = []
    for key in ("canary", "verdict", "critical_issues", "suggestions", "confidence"):
        if key not in v:
            errs.append(f"missing field: {key}")
    if errs:
        return errs

    if v["verdict"] not in {"PASS", "FAIL"}:
        errs.append(f"bad verdict: {v['verdict']!r}")
    if v["confidence"] not in _CONFIDENCE:
        errs.append(f"bad confidence: {v['confidence']!r}")
    if not isinstance(v["critical_issues"], list):
        errs.append("critical_issues is not a list")
    if not isinstance(v["suggestions"], list):
        errs.append("suggestions is not a list")

    for i, issue in enumerate(v.get("critical_issues") or []):
        if not isinstance(issue, dict):
            errs.append(f"critical_issues[{i}] is not an object")
            continue
        sev = issue.get("severity")
        if sev not in _SEVERITIES:
            errs.append(f"critical_issues[{i}].severity={sev!r}")

    # The rubric says FAIL iff critical_issues is non-empty. A reviewer that
    # violates this is not following the rubric, so its verdict is unusable.
    if isinstance(v.get("critical_issues"), list):
        expect = "FAIL" if v["critical_issues"] else "PASS"
        if v["verdict"] != expect:
            errs.append(f"verdict={v['verdict']} contradicts "
                        f"{len(v['critical_issues'])} critical_issues")
    return errs


def _canary_errors(verdict: dict, expected_first_file: str,
                   expected_file_count: int) -> list[str]:
    canary = verdict.get("canary")
    if not isinstance(canary, dict):
        return ["canary missing or not an object -- cannot prove the reviewer saw the diff"]

    errs: list[str] = []
    got_file = canary.get("first_changed_file")
    got_count = canary.get("changed_file_count")
    if got_file != expected_first_file:
        errs.append(f"canary.first_changed_file={got_file!r} expected "
                    f"{expected_first_file!r} -- reviewer did not see the diff")
    if got_count != expected_file_count:
        errs.append(f"canary.changed_file_count={got_count!r} "
                    f"expected {expected_file_count} -- reviewer did not see the diff")
    return errs


def validate(verdict: dict | None, expected_first_file: str,
             expected_file_count: int) -> Validation:
    if verdict is None:
        return Validation(INVALID, ["no parseable JSON verdict"])

    # Canary first: when a reviewer never saw the diff it also tends to violate
    # the rubric, and reporting the rubric breach would name a symptom instead
    # of the cause.
    errs = _canary_errors(verdict, expected_first_file, expected_file_count)
    errs += _shape_errors(verdict)
    return Validation(INVALID if errs else VALID, errs)
