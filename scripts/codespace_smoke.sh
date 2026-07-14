#!/usr/bin/env bash
# Codespaces 冒烟：验证 SWE-bench 评测链路能跑通，再谈实验。
#
# 用 gold patch 跑评测——正确的话应该 100% resolved。
# 如果 gold 都过不了，说明是环境问题，不是模型问题。这一步不通，后面全是空中楼阁。
#
# 磁盘策略：只挑「同一个 repo」的 N 条 instance，它们共用一个环境镜像，
# 磁盘占用因此只有 10-30GB，而不是全量的 120GB。
set -euo pipefail

N=${N:-10}
RUN_ID=${RUN_ID:-smoke}
WORKERS=${WORKERS:-4}

echo "=========== [1/5] 环境自检 ==========="
echo "arch    : $(uname -m)   (SWE-bench 要求 x86_64)"
echo "cpu     : $(nproc) 核"
echo "mem     : $(free -g | awk '/^Mem:/{print $2}') GB   (要求 >= 16)"
echo "disk    : $(df -h / | awk 'NR==2{print $4}') 可用   (要求 >= 120G)"
echo

echo "=========== [2/5] Docker 是否可用 ==========="
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker 不可用 —— devcontainer 的 docker-in-docker feature 没生效。"
  echo "   检查 .devcontainer/devcontainer.json，然后 Rebuild Container。"
  exit 1
fi
echo "✅ Docker OK: $(docker --version)"
echo

echo "=========== [3/5] 挑 $N 条同 repo 的 instance ==========="
python - "$N" <<'PY'
import sys, json, collections
from datasets import load_dataset

n = int(sys.argv[1])
ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

# 按 (repo, version) 分组 —— 同组共用一个环境镜像，这是控磁盘的关键。
groups = collections.defaultdict(list)
for r in ds:
    groups[(r["repo"], r["version"])].append(r["instance_id"])

# 挑 instance 数量最多的那一组，最大化「一个镜像覆盖多条」
(repo, ver), ids = max(groups.items(), key=lambda kv: len(kv[1]))
picked = sorted(ids)[:n]

print(f"数据集共 {len(ds)} 条，{len(groups)} 个 (repo, version) 环境组")
print(f"选中: {repo} @ {ver}  —— 该组共 {len(ids)} 条，取前 {len(picked)} 条")
print(f"→ 只需构建 1 个环境镜像")
with open("smoke_instances.json", "w") as f:
    json.dump(picked, f, indent=2)
for i in picked:
    print("   ", i)
PY
echo

echo "=========== [4/5] 用 gold patch 跑评测（预期 100% resolved）==========="
IDS=$(python -c "import json;print(' '.join(json.load(open('smoke_instances.json'))))")
# shellcheck disable=SC2086
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --predictions_path gold \
  --run_id "$RUN_ID" \
  --instance_ids $IDS \
  --max_workers "$WORKERS" \
  --cache_level env          # 绝不用 instance —— 那要 2TB
echo

echo "=========== [5/5] 结果 ==========="
REPORT=$(ls -t *."$RUN_ID".json 2>/dev/null | head -1 || true)
if [ -n "$REPORT" ]; then
  python -c "
import json,sys
r=json.load(open('$REPORT'))
print('total     :', r.get('total_instances'))
print('completed :', r.get('completed_instances'))
print('resolved  :', r.get('resolved_instances'))
print('unresolved:', r.get('unresolved_instances'))
print('errors    :', r.get('error_instances'))
ok = r.get('resolved_instances')==r.get('total_instances')
print()
print('✅ 链路通了——gold patch 全部 resolved，可以进入难度筛选。' if ok
      else '❌ gold patch 没有全过 —— 这是环境问题，不是模型问题。先修这个。')
"
else
  echo "❌ 没找到评测报告，检查上面的输出"
fi
echo
echo "磁盘占用:"; df -h / | awk 'NR==2{print "  根分区已用 "$3" / 共 "$2"  (剩 "$4")"}'
docker system df 2>/dev/null | head -3
