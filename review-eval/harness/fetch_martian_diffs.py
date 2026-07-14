"""拉取 Martian 30 个 PR 的 diff。

Martian 数据集只给了 PR url + 人工确认的 golden review comments，**没有 diff**。
走 GitHub 公开的 `.diff` URL，不需要 gh CLI，也不需要 auth（本机 gh 未安装）。

注意 Martian 在本实验里的角色与另外两个数据集不同：
它没有可执行测试，不参与难度筛选。它直接评估 reviewer 的缺陷发现能力
（golden comment 召回率 / 误报率），与 BugsInPy/Polyglot 的端到端增益评估互补。
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest" / "martian-30.json"
OUT = ROOT / "cases" / "martian"
UA = {"User-Agent": "multi-agent-eval/1.0"}
MAX_DIFF_BYTES = 2_000_000  # 超大 PR 直接标记，不静默截断


def fetch(url: str, retries: int = 3) -> tuple[str | None, str | None]:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read(MAX_DIFF_BYTES + 1)
                if len(raw) > MAX_DIFF_BYTES:
                    return None, f"diff > {MAX_DIFF_BYTES} bytes（超大 PR，单独处理）"
                return raw.decode("utf-8", errors="replace"), None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < retries:
                time.sleep(5 * attempt)  # 限流，退避重试
                continue
            return None, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            if attempt < retries:
                time.sleep(2 * attempt)
                continue
            return None, repr(e)
    return None, "retries exhausted"


def main():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    OUT.mkdir(parents=True, exist_ok=True)

    ok = failed = skipped = 0
    report = []
    for i, c in enumerate(cases, 1):
        d = OUT / c["id"]
        d.mkdir(exist_ok=True)
        diff_path = d / "pr.diff"

        if diff_path.exists() and diff_path.stat().st_size > 0:
            skipped += 1
            status = "cached"
        else:
            diff, err = fetch(c["diff_url"])
            if diff is None:
                failed += 1
                status = f"FAIL: {err}"
                report.append({"id": c["id"], "url": c["url"], "error": err})
            else:
                diff_path.write_text(diff, encoding="utf-8")
                ok += 1
                status = f"{len(diff):,} bytes"
            time.sleep(1)  # 对 github.com 温柔一点

        # golden comments 与 case 元数据一起落盘，供 judge 阶段使用
        (d / "golden.json").write_text(
            json.dumps({
                "id": c["id"], "repo": c["repo"], "url": c["url"],
                "pr_title": c["pr_title"],
                "golden_comments": c["golden_comments"],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[{i:2d}/{len(cases)}] {c['id']:34s} {status}")

    print(f"\n拉取成功 {ok} / 缓存跳过 {skipped} / 失败 {failed}")
    if report:
        p = OUT / "_failed.json"
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"失败清单 -> {p.relative_to(ROOT)}（不要静默忽略，这些 case 要么补拉要么从样本里剔除并记录）")


if __name__ == "__main__":
    main()
