"""Orchestrate the multi-arm review experiment.

Usage:
  python harness/run.py --crb <path-to-code-review-benchmark> --repos sentry \
      --items 3 --reps 1 --out results/pilot
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import judge
import package
import reviewers
import validate

# Arms differ ONLY in the reviewer. The implementer dimension (and therefore the
# shared-context self-review arm) needs a write-then-review experiment; on a
# fixed golden PR set nobody "wrote" the code, so self-review is undefined here.
ARMS = [
    {"name": "codex-gpt5.5", "backend": "codex", "model": "gpt-5.5", "effort": "medium"},
    {"name": "claude-opus", "backend": "claude", "model": "claude-opus-4-8", "effort": "medium"},
]


def load_items(crb: Path, repos: list[str], limit: int) -> list[dict]:
    items: list[dict] = []
    for repo in repos:
        path = crb / "offline" / "golden_comments" / f"{repo}.json"
        for i, pr in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            items.append({
                "item_id": f"{repo}-{i}",
                "url": pr["url"],
                "title": pr["pr_title"],
                "golden": pr["comments"],
            })
    return items[:limit] if limit else items


REPAIR = ("\n\n## Your previous reply was rejected\n{errors}\n"
          "Re-emit the FULL JSON object using exactly the schema field names. "
          "No prose, no markdown fence.\n")


def _invoke(arm: dict, prompt: str, workdir: Path) -> reviewers.RunResult:
    if arm["backend"] == "codex":
        return reviewers.review_codex(prompt, arm["model"], arm["effort"], workdir)
    return reviewers.review_claude(prompt, arm["model"], arm["effort"], workdir)


def run_arm(arm: dict, pkg: package.Package,
            workdir: Path) -> tuple[reviewers.RunResult, validate.Validation, int]:
    """One bounded repair attempt, granted symmetrically to both backends.

    Without it the comparison measures schema compliance rather than review
    skill: `codex exec` enforces the shape via --output-schema, `claude -p`
    cannot, so a reviewer that finds the real bug but names its fields wrong
    would score zero.
    """
    res = _invoke(arm, pkg.prompt, workdir)
    v = validate.validate(res.verdict, pkg.first_changed_file, pkg.changed_file_count)
    if v.ok:
        return res, v, 0

    repaired = pkg.prompt + REPAIR.format(errors="\n".join(f"- {r}" for r in v.reasons))
    res2 = _invoke(arm, repaired, workdir)
    v2 = validate.validate(res2.verdict, pkg.first_changed_file, pkg.changed_file_count)
    return res2, v2, 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crb", required=True, type=Path)
    ap.add_argument("--repos", nargs="+", default=["sentry"])
    ap.add_argument("--items", type=int, default=3)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "work"
    records: list[dict] = []
    skipped: list[dict] = []

    for item in load_items(args.crb, args.repos, args.items):
        try:
            diff = package.fetch_diff(item["url"])
            pkg = package.build(item["item_id"], item["url"], item["title"], diff)
        except (package.DiffTooLarge, ValueError) as e:
            skipped.append({"item_id": item["item_id"], "reason": str(e)})
            print(f"SKIP {item['item_id']}: {e}")
            continue

        package.write(pkg, args.out / "packages")
        print(f"\n=== {pkg.item_id}  sha256={pkg.sha256[:12]}  "
              f"files={pkg.changed_file_count}  golden={len(item['golden'])}")

        for arm in ARMS:
            for rep in range(args.reps):
                res, v, repairs = run_arm(arm, pkg, work / arm["name"])
                findings = (res.verdict or {}).get("critical_issues", []) if v.ok else []
                status, judge_error, pairs = v.status, None, []
                if v.ok:
                    try:
                        pairs = judge.match(findings, item["golden"])
                    except judge.JudgeError as e:
                        # A judge outage is not evidence of zero recall.
                        status, judge_error = "JUDGE_ERROR", str(e)

                rec = {
                    "item_id": pkg.item_id, "sha256": pkg.sha256, "rep": rep,
                    "arm": arm["name"], "backend": arm["backend"],
                    "model": arm["model"], "effort": arm["effort"],
                    "status": status, "reasons": v.reasons, "repairs": repairs,
                    "judge_error": judge_error,
                    "verdict": (res.verdict or {}).get("verdict"),
                    "n_findings": len(findings),
                    "n_golden": len(item["golden"]),
                    "n_matched": len(pairs),
                    "matched_golden": sorted(g for g, _ in pairs),
                    "duration_ms": res.duration_ms, "cost_usd": res.cost_usd,
                    "tokens": res.tokens, "schema_failure": res.schema_failure,
                    "error": res.error,
                }
                records.append(rec)
                if status == "JUDGE_ERROR":
                    flag = "JUDGE_ERROR"
                elif v.ok:
                    flag = "ok" if not repairs else "ok(repaired)"
                else:
                    flag = f"INVALID {v.reasons[:1]}"
                print(f"  {arm['name']:14} {flag:38} "
                      f"findings={len(findings):2} matched={len(pairs)}/{len(item['golden'])} "
                      f"{res.duration_ms}ms")

    (args.out / "records.json").write_text(
        json.dumps({"records": records, "skipped": skipped}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    summarize(records, skipped)


def summarize(records: list[dict], skipped: list[dict]) -> None:
    print("\n" + "=" * 82)
    print(f"{'arm':16}{'valid':>7}{'invalid':>9}{'repaired':>10}"
          f"{'recall':>9}{'precision':>11}{'med_ms':>9}")
    print("-" * 82)
    for arm in sorted({r["arm"] for r in records}):
        rs = [r for r in records if r["arm"] == arm]
        ok = [r for r in rs if r["status"] == validate.VALID]
        bad = [r for r in rs if r["status"] == validate.INVALID]
        je = [r for r in rs if r["status"] == "JUDGE_ERROR"]
        if je:
            print(f"  (note: {arm} had {len(je)} judge outage(s), excluded from rates)")
        rep = sum(r.get("repairs", 0) for r in rs)
        if not ok:
            print(f"{arm:16}{0:>7}{len(bad):>9}{rep:>10}{'-':>9}{'-':>11}{'-':>9}")
            continue
        matched = sum(r["n_matched"] for r in ok)
        golden = sum(r["n_golden"] for r in ok)
        found = sum(r["n_findings"] for r in ok)
        recall = matched / golden if golden else 0.0
        prec = matched / found if found else 0.0
        med = statistics.median(r["duration_ms"] for r in ok)
        print(f"{arm:16}{len(ok):>7}{len(bad):>9}{rep:>10}"
              f"{recall:>8.1%}{prec:>11.1%}{med:>9.0f}")

    # Overlap is the number that decides whether cross-model buys anything.
    arms = sorted({r["arm"] for r in records})
    if len(arms) == 2:
        a, b = arms
        inter = union = 0
        for item in sorted({r["item_id"] for r in records}):
            ga = {g for r in records if r["item_id"] == item and r["arm"] == a
                  and r["status"] == validate.VALID for g in r["matched_golden"]}
            gb = {g for r in records if r["item_id"] == item and r["arm"] == b
                  and r["status"] == validate.VALID for g in r["matched_golden"]}
            inter += len(ga & gb)
            union += len(ga | gb)
        print("-" * 72)
        print(f"overlap (Jaccard over matched golden): {inter}/{union} = "
              f"{inter/union:.1%}" if union else "overlap: n/a (no matches)")
    if skipped:
        print(f"\nskipped {len(skipped)} item(s): "
              f"{[s['item_id'] for s in skipped]}  (never silently truncated)")


if __name__ == "__main__":
    main()
