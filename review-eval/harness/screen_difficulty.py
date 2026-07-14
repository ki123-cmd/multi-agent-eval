"""难度筛选：对每个 case 跑 k 次 CC-only，按 pass 次数分档，产出黄金样本池。

这是整个实验的前置阻塞：手搓样本 CC-only 3/3 全过 = 天花板效应，
协作增益无处可测。只有 pass rate 落在 (0, 1) 开区间的 case 才有区分度。

  5/5  -> 丢弃（天花板）
  0/5  -> 地板组（review 大概率也救不回来，单独记录）
  1-4/5 -> 黄金样本 ★

用法:
  python harness/screen_difficulty.py                # 全量 30 case × 5 次
  python harness/screen_difficulty.py --limit 2 -k 1 # 冒烟
  python harness/screen_difficulty.py --report       # 只汇总已有结果，不跑
"""
import argparse
import json
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from polyglot_runner import run_once

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest" / "polyglot-30.json"
RESULTS = ROOT / "screening" / "cc_only_runs.jsonl"
POOL = ROOT / "screening" / "golden_pool.json"
WORK = ROOT / "work" / "screening"


def load_done() -> set:
    """已成功完成的 (case_id, k)，用于断点续跑。

    基础设施故障的运行**不算完成**——它们会在下次运行时自动重试，
    而不是被当成"这个 case 已经跑过了、CC 没做出来"。
    """
    if not RESULTS.exists():
        return set()
    done = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["cc"].get("ok"):
                done.add((r["case_id"], r["k"]))
    return done


def append(record: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def report(min_valid: int = 2) -> dict:
    """按 case 聚合 pass 次数并分档。

    基础设施故障（CC 没启动、超时、崩溃）必须排除在 pass rate 的分母之外。
    否则"claude 没跑起来"和"CC 做错了题"在数据上无法区分——这正是官方 Codex 插件
    Stop hook 的 fail-closed 缺陷（超时 / 非零退出 / JSON 解析失败全都走 block 分支）。
    """
    runs = defaultdict(list)
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                runs[r["case_id"]].append(r)

    buckets = {"golden": [], "ceiling": [], "floor": [], "partial": [], "infra_error": []}
    for cid, rs in sorted(runs.items()):
        valid = [r for r in rs if r["cc"].get("ok")]          # 只有 CC 真跑起来的才算数
        n_err = len(rs) - len(valid)
        k = len(valid)
        n_pass = sum(1 for r in valid if r["score"]["passed"])
        entry = {"case_id": cid, "k_valid": k, "n_pass": n_pass, "n_infra_error": n_err,
                 "pass_rate": round(n_pass / k, 2) if k else None}
        if n_err:
            buckets["infra_error"].append(entry)              # 单独记账，需重跑
        if k < min_valid:
            buckets["partial"].append(entry)                  # 有效运行不足，无法分档
        elif n_pass == k:
            buckets["ceiling"].append(entry)
        elif n_pass == 0:
            buckets["floor"].append(entry)
        else:
            buckets["golden"].append(entry)                   # ★
    return buckets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=5, help="每个 case 重复次数")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个 case（冒烟用）")
    ap.add_argument("--workers", type=int, default=4, help="并发数")
    ap.add_argument("--report", action="store_true", help="只汇总，不跑")
    args = ap.parse_args()

    if not args.report:
        cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
        if args.limit:
            cases = cases[: args.limit]

        done = load_done()
        todo = [(c, i) for c in cases for i in range(1, args.k + 1)
                if (c["id"], i) not in done]
        print(f"cases={len(cases)}  k={args.k}  todo={len(todo)}  (已完成 {len(done)} 次运行，跳过)")

        if todo:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = {
                    pool.submit(run_once, c, WORK / f"{c['id']}__k{i}"): (c, i)
                    for c, i in todo
                }
                for n, fut in enumerate(as_completed(futs), 1):
                    c, i = futs[fut]
                    try:
                        rec = fut.result()
                    except Exception as e:  # 单个 case 炸了不能拖垮整轮
                        rec = {"case_id": c["id"], "cc": {"ok": False, "error": repr(e)},
                               "score": {"passed": False, "n_passed": 0, "n_failed": -1, "tail": ["EXC"]}}
                    rec["k"] = i
                    append(rec)
                    flag = "PASS" if rec["score"]["passed"] else "FAIL"
                    print(f"[{n}/{len(todo)}] {rec['case_id']} k={i} {flag}")

        shutil.rmtree(WORK, ignore_errors=True)

    b = report()
    POOL.parent.mkdir(parents=True, exist_ok=True)
    POOL.write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n===== 难度分档 =====")
    print(f"  ★ 黄金 (1..k-1 通过)  {len(b['golden']):3d}   <- 唯一有区分度的样本")
    print(f"    天花板 (k/k 通过)   {len(b['ceiling']):3d}   <- 丢弃")
    print(f"    地板   (0/k 通过)   {len(b['floor']):3d}")
    print(f"    有效运行不足        {len(b['partial']):3d}")
    print(f"    基础设施故障        {len(b['infra_error']):3d}   <- 不计入 pass rate，重跑即可")
    for e in b["golden"]:
        print(f"      ★ {e['case_id']:38s} {e['n_pass']}/{e['k_valid']}")
    print(f"\n-> {POOL.relative_to(ROOT)}")
    if len(b["golden"]) < 20 and not b["partial"]:
        print("\n⚠️  黄金样本 < 20：CC 在本数据集上要么太强要么太弱，"
              "需要换数据集或加难度——这个结论必须在建完整 runner 之前知道。")


if __name__ == "__main__":
    main()
