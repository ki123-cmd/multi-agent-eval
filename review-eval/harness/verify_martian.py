"""Martian 数据完整性校验：确认本地 diff 与 GitHub 自报的 changed_files 一致。

背景：这些 PR 是 Martian 有意构造的合成 PR（fork 到 ai-code-review-evaluation 组，
在分支上注入缺陷）。部分 PR 的 base 不是 master 而是另一个特性分支，甚至多个 PR
共用同一个 head 分支 —— 导致不同 PR 的 diff 互相重叠。

这不是我们的拉取错误，而是基准自带的结构性特征：golden comments 正是让评审工具
在 GitHub 上看这个 diff 产生的，所以本地 diff 必须与 GitHub 的视图逐字一致。

本脚本用 GitHub 自报的 changed_files 与本地 diff 的文件数对账，坐实这一点；
同时记录 PR 之间的 diff 重叠，作为误报率分析时必须扣除的已知偏差。
"""
import json
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest" / "martian-30.json"
CASES = ROOT / "cases" / "martian"
OUT = ROOT / "cases" / "martian" / "_integrity.json"
UA = {"User-Agent": "multi-agent-eval/1.0"}


def api(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"    API 失败: {e}")
        return None


def files_in_diff(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.split(" b/", 1)[0].replace("diff --git a/", "")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith("diff --git ")
    ]


def main():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    records, mismatched = [], []
    by_repo_files = defaultdict(dict)

    for i, c in enumerate(cases, 1):
        owner_repo = c["url"].split("github.com/")[1].split("/pull/")[0]
        pr_num = c["url"].rstrip("/").split("/")[-1]
        meta = api(f"https://api.github.com/repos/{owner_repo}/pulls/{pr_num}")
        local = files_in_diff(CASES / c["id"] / "pr.diff")
        by_repo_files[owner_repo][c["id"]] = set(local)

        if meta is None:
            rec = {"id": c["id"], "status": "api_error", "local_files": len(local)}
        else:
            gh_n = meta.get("changed_files")
            ok = gh_n == len(local)
            rec = {
                "id": c["id"], "status": "ok" if ok else "MISMATCH",
                "base_ref": meta["base"]["ref"], "head_ref": meta["head"]["ref"],
                "github_changed_files": gh_n, "local_files": len(local),
                "commits": meta.get("commits"),
                "n_golden_comments": c["n_golden_comments"],
            }
            if not ok:
                mismatched.append(rec)
        records.append(rec)
        print(f"[{i:2d}/30] {c['id']:34s} {rec['status']:8s} "
              f"gh={rec.get('github_changed_files','?')} local={rec['local_files']}")
        time.sleep(1)  # 未认证的 GitHub API 限流 60/小时

    # PR 之间的 diff 重叠：基准自带偏差，误报率分析时必须扣除
    overlaps = []
    for repo, m in by_repo_files.items():
        ids = sorted(m)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                shared = m[ids[a]] & m[ids[b]]
                if shared:
                    overlaps.append({
                        "repo": repo, "pair": [ids[a], ids[b]],
                        "shared_files": sorted(shared),
                    })

    OUT.write_text(json.dumps(
        {"records": records, "mismatched": mismatched, "diff_overlaps": overlaps},
        indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n对账一致 {sum(1 for r in records if r['status'] == 'ok')}/30，"
          f"不一致 {len(mismatched)}，API 失败 {sum(1 for r in records if r['status'] == 'api_error')}")
    print(f"存在 diff 重叠的 PR 对：{len(overlaps)} 组 —— 已知偏差，reviewer 会对不属于本 PR 的")
    print("代码提意见，而 golden comments 不覆盖它们。误报率统计时必须把重叠文件上的意见单独归类。")
    print(f"\n-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
