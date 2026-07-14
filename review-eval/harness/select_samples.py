"""确定性抽样：从三个数据集各取 30 条，产出 manifest。

固定 seed，可复现。抽样帧（sampling frame）的任何限制都会写进 manifest 的 _meta 里，
作为 threat to validity 记录在案。
"""
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
MANIFEST = ROOT / "manifest"
SEED = 42
N = 30

# BugsInPy：501 个 bug 分布在 17 个项目里，但每个项目要求特定的旧版 Python
# (3.6.9 / 3.7.x / 3.8.x) 且需 clone 真实仓库、装当年的依赖。
# 限制抽样帧为「纯 Python、依赖轻」的项目——排除 pandas/keras/matplotlib/scrapy/
# spacy/ansible 这类带 C 扩展或重型依赖的，否则环境搭建成本会吞掉整个项目。
# 这是一个有意的抽样帧限制，必须在论文里作为 threat to validity 声明。
BUGSINPY_LIGHT = [
    "PySnooper", "black", "cookiecutter", "httpie", "luigi",
    "sanic", "thefuck", "tqdm", "youtube-dl",
]


def parse_info(path: Path) -> dict:
    """BugsInPy 的 .info 文件是 key="value" 行。"""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^(\w+)\s*=\s*"?([^"]*)"?\s*$', line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def select_bugsinpy(rng) -> dict:
    frame = []
    for proj in sorted(BUGSINPY_LIGHT):
        bugs_dir = SOURCES / "BugsInPy" / "projects" / proj / "bugs"
        if not bugs_dir.is_dir():
            continue
        for bug in sorted(bugs_dir.iterdir(), key=lambda p: int(p.name)):
            info = parse_info(bug / "bug.info")
            patch = bug / "bug_patch.txt"
            if not patch.exists():
                continue
            frame.append({
                "id": f"bugsinpy-{proj}-{bug.name}",
                "project": proj,
                "bug_id": int(bug.name),
                "python_version": info.get("python_version", ""),
                "buggy_commit": info.get("buggy_commit_id", ""),
                "fixed_commit": info.get("fixed_commit_id", ""),
                "test_file": info.get("test_file", ""),
                "golden_patch": str(patch.relative_to(ROOT)),
                "run_test": (bug / "run_test.sh").read_text(
                    encoding="utf-8", errors="replace").strip(),
            })
    picked = sorted(rng.sample(frame, min(N, len(frame))), key=lambda c: c["id"])
    return {
        "_meta": {
            "dataset": "BugsInPy",
            "task_type": "bug-fix (real historical bugs)",
            "metric": "hidden test pass/fail",
            "golden": "bug_patch.txt (官方修复 diff)",
            "seed": SEED,
            "frame_size": len(frame),
            "frame_restriction": (
                "仅限纯 Python、依赖轻的 9 个项目；排除 pandas/keras/matplotlib/"
                "scrapy/spacy/ansible/tornado/fastapi。THREAT TO VALIDITY：样本不代表全部 501 条。"
            ),
            "execution_blocker": (
                "需要 pyenv + Python 3.6/3.7/3.8 + clone 真实仓库。本机无 WSL/Docker，"
                "当前仅能做离线部分（元数据 + golden patch）。"
            ),
        },
        "cases": picked,
    }


def select_polyglot(rng) -> dict:
    # Python 子集：自包含（题面 + 桩 + 测试 + golden 解都在本地），只需 pytest。
    # 34 个 exercise 里取 30，是三个数据集中唯一今天就能跑的。
    base = SOURCES / "polyglot-benchmark" / "python" / "exercises" / "practice"
    frame = []
    for ex in sorted(base.iterdir()):
        if not ex.is_dir():
            continue
        slug = ex.name
        stub = ex / f"{slug.replace('-', '_')}.py"
        test = ex / f"{slug.replace('-', '_')}_test.py"
        example = ex / ".meta" / "example.py"
        docs = ex / ".docs" / "instructions.md"
        if not (stub.exists() and test.exists() and example.exists()):
            continue
        frame.append({
            "id": f"polyglot-py-{slug}",
            "slug": slug,
            "lang": "python",
            "stub": str(stub.relative_to(ROOT)),
            "test": str(test.relative_to(ROOT)),
            "golden": str(example.relative_to(ROOT)),
            "docs": str(docs.relative_to(ROOT)) if docs.exists() else "",
        })
    picked = sorted(rng.sample(frame, min(N, len(frame))), key=lambda c: c["id"])
    return {
        "_meta": {
            "dataset": "Aider Polyglot (python subset)",
            "task_type": "feature implementation (exercism)",
            "metric": "test pass/fail",
            "golden": ".meta/example.py (官方参考解)",
            "seed": SEED,
            "frame_size": len(frame),
            "frame_restriction": "仅 python 子集（34 个）。其他 5 种语言需各自工具链。",
            "execution_blocker": "无。只需 pip install pytest。",
        },
        "cases": picked,
    }


def select_martian(rng) -> dict:
    # Martian：只有 PR url + golden review comments（无 diff，需联网拉）。
    # 注意：它是 review 召回率 benchmark，没有 pass/fail 测试 —— 不参与难度筛选。
    gc_dir = SOURCES / "code-review-benchmark" / "offline" / "golden_comments"
    frame = []
    for f in sorted(gc_dir.glob("*.json")):
        repo = f.stem
        for pr in json.loads(f.read_text(encoding="utf-8")):
            comments = pr.get("comments", [])
            if not comments:
                continue
            frame.append({
                "id": f"martian-{repo}-{pr['url'].rstrip('/').split('/')[-1]}",
                "repo": repo,
                "pr_title": pr.get("pr_title", ""),
                "url": pr["url"],
                "diff_url": pr["url"].rstrip("/") + ".diff",
                "n_golden_comments": len(comments),
                "severities": sorted({c.get("severity", "?") for c in comments}),
                "golden_comments": comments,
            })
    picked = sorted(rng.sample(frame, min(N, len(frame))), key=lambda c: c["id"])
    return {
        "_meta": {
            "dataset": "Martian Code Review Benchmark",
            "task_type": "code review (golden comment recall)",
            "metric": "golden comment 召回率 / 误报率 —— 不是 pass/fail",
            "golden": "人工确认的 golden review comments（含 severity）",
            "seed": SEED,
            "frame_size": len(frame),
            "role": (
                "本数据集不参与难度筛选（没有可执行测试）。它的作用是直接评估 reviewer "
                "的缺陷发现能力，与 BugsInPy/Polyglot 的端到端增益评估互补。"
            ),
            "execution_blocker": "需联网拉 PR diff（走公开 .diff URL，无需 gh/auth）。",
        },
        "cases": picked,
    }


def main():
    MANIFEST.mkdir(exist_ok=True)
    for name, fn in [
        ("bugsinpy", select_bugsinpy),
        ("polyglot", select_polyglot),
        ("martian", select_martian),
    ]:
        data = fn(random.Random(SEED))
        out = MANIFEST / f"{name}-30.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        m = data["_meta"]
        print(f"{name:10s} {len(data['cases']):3d} / frame {m['frame_size']:4d}  -> {out.name}")


if __name__ == "__main__":
    main()
