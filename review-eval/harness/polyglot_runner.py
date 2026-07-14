"""Polyglot 单 case runner：物化 → CC-only 实现 → 隐藏测试评分。

关键设计：**测试文件不进 CC 的工作目录**。
CC 只看到 instructions + 待实现的桩，测试是 held-out 的（与 Aider 官方协议一致）。
否则 CC 自己跑测试迭代到全绿，pass rate 必然触顶，实验失去区分度。
"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Windows 上 `claude` 是 npm 的 .cmd 垫片，subprocess 不走 shell 时必须给到实际可执行文件，
# 否则报 FileNotFoundError —— 而那是基础设施故障，绝不能被记成"CC 没做出来"。
CLAUDE = shutil.which("claude") or shutil.which("claude.cmd")
if CLAUDE is None:
    raise RuntimeError("找不到 claude CLI，请确认已安装且在 PATH 中")

CC_PROMPT = """\
Implement the solution for this exercise.

{instructions}

Edit the file `{stub_name}` to make the implementation complete and correct.
Do not create any other files. Do not write tests.
The public API (function/class names and signatures) in the stub must be preserved.
"""


def materialize(case: dict, run_dir: Path) -> Path:
    """把一个 case 物化成干净的工作目录。不含测试文件。"""
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    stub_src = ROOT / case["stub"]
    shutil.copy2(stub_src, run_dir / stub_src.name)

    if case.get("docs"):
        docs_src = ROOT / case["docs"]
        docs_dst = run_dir / ".docs"
        docs_dst.mkdir()
        shutil.copy2(docs_src, docs_dst / docs_src.name)
        extra = docs_src.parent / "instructions.append.md"
        if extra.exists():
            shutil.copy2(extra, docs_dst / extra.name)
    return run_dir


def read_instructions(case: dict) -> str:
    if not case.get("docs"):
        return f"Exercise: {case['slug']}"
    p = ROOT / case["docs"]
    text = p.read_text(encoding="utf-8", errors="replace")
    extra = p.parent / "instructions.append.md"
    if extra.exists():
        text += "\n\n" + extra.read_text(encoding="utf-8", errors="replace")
    return text


def _parse_result_json(stdout: str) -> dict | None:
    """从 stdout 里取出 claude 的 result JSON。

    容忍 stdout 里混入其他行（例如坏掉的插件 hook 打的噪音）——只认能解析成
    JSON 对象、且带 type=result 的那一行。
    """
    stdout = (stdout or "").strip()
    if not stdout:
        return None
    try:
        obj = json.loads(stdout)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            return obj
    return None


def run_cc(case: dict, run_dir: Path, timeout: int = 600) -> dict:
    """无头调用 Claude Code 产出第一版实现。

    prompt 走 stdin，不走 argv —— Windows CreateProcess 的命令行上限是 8191 字符，
    题面长的 case（如 beer-song）用 argv 传会直接报"命令行太长"，
    而那是基础设施故障，会被误记成"CC 没做出来"。
    """
    stub_name = Path(case["stub"]).name
    prompt = CC_PROMPT.format(
        instructions=read_instructions(case), stub_name=stub_name
    )
    cmd = [
        CLAUDE, "-p",
        "--output-format", "json",
        "--allowedTools", "Read", "Write", "Edit",
        "--permission-mode", "acceptEdits",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=run_dir, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "wall_s": round(time.time() - t0, 1)}

    wall = round(time.time() - t0, 1)
    payload = _parse_result_json(proc.stdout)
    if proc.returncode != 0 or payload is None:
        return {
            "ok": False, "wall_s": wall, "returncode": proc.returncode,
            "error": (proc.stderr or proc.stdout or "").strip()[-400:],
        }

    usage = payload.get("usage") or {}
    return {
        "ok": not payload.get("is_error", False),
        "wall_s": wall,
        "cost_usd": payload.get("total_cost_usd"),
        "duration_ms": payload.get("duration_ms"),
        "num_turns": payload.get("num_turns"),
        "session_id": payload.get("session_id"),
        "output_tokens": usage.get("output_tokens"),
        "input_tokens": usage.get("input_tokens"),
    }


def score(case: dict, run_dir: Path, timeout: int = 120) -> dict:
    """把 held-out 测试拷进去跑，跑完删掉——测试永远不留在 CC 的工作目录里。"""
    test_src = ROOT / case["test"]
    test_dst = run_dir / test_src.name
    shutil.copy2(test_src, test_dst)
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", test_dst.name, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=run_dir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        passed = _count(out, "passed")
        failed = _count(out, "failed") + _count(out, "error")
        return {
            "passed": proc.returncode == 0,
            "n_passed": passed,
            "n_failed": failed,
            "tail": out.strip().splitlines()[-3:] if out.strip() else [],
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "n_passed": 0, "n_failed": -1, "tail": ["TIMEOUT"]}
    finally:
        test_dst.unlink(missing_ok=True)
        shutil.rmtree(run_dir / ".pytest_cache", ignore_errors=True)
        shutil.rmtree(run_dir / "__pycache__", ignore_errors=True)


def _count(text: str, word: str) -> int:
    m = re.search(rf"(\d+) {word}", text)
    return int(m.group(1)) if m else 0


def run_once(case: dict, run_dir: Path) -> dict:
    """一次完整的 CC-only 运行：物化 → CC 实现 → 隐藏测试评分。"""
    materialize(case, run_dir)
    cc = run_cc(case, run_dir)
    sc = score(case, run_dir) if cc["ok"] else {"passed": False, "n_passed": 0, "n_failed": -1, "tail": ["CC_FAILED"]}
    return {"case_id": case["id"], "cc": cc, "score": sc}
