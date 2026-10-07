#!/usr/bin/env bash
# 一键验证：把 AGENTS.md「验证环境」里的固定步骤合成一条命令，省掉反复来回调用。
#
# 用法：
#   scripts/check.sh                                  # 静态检查：compileall + 改动 JS 的 node --check + handoff 体积预算 + git diff --check
#   scripts/check.sh tests.test_resource_ed2k         # 追加指定 unittest 用例（可传多个）
#   scripts/check.sh --all                            # 跑全量 unittest（发布 / 合并前用）
#   scripts/check.sh --js static/js/index.js          # 手动指定要 node --check 的 JS（可重复）
#   scripts/check.sh -h                               # 查看本说明
#
# 约定：
#   - Python 用项目本地 .venv/bin/python，字节码缓存写 /tmp（不污染工作区）
#   - 未显式传 --js 时，自动取 git 里「改动 / 新增」的 .js 文件
#   - 顺带检查 docs/superpowers/handoff.md 体积预算（默认 32768 字节，可用 HANDOFF_BUDGET_BYTES 覆盖）
#   - 任一步失败即返回非 0，并打印失败摘要
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${CHECK_PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/115-media-hub-pycache}"

test_targets=()
js_targets=()
run_all=0

while [ $# -gt 0 ]; do
  case "$1" in
    --all) run_all=1 ;;
    --js)
      shift
      [ -n "${1:-}" ] && js_targets+=("$1")
      ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      test_targets+=("$1")
      ;;
  esac
  shift
done

failed=0
step() { printf '\n== %s ==\n' "$1"; }

step "compileall app main.py"
"$PYTHON" -m compileall -q app main.py || failed=1

if [ "${#js_targets[@]}" -eq 0 ]; then
  # 自动收集本次改动 / 新增的 JS（含未跟踪文件），避免全量扫描
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    [ -f "$path" ] || continue
    case "$path" in
      *.js) js_targets+=("$path") ;;
    esac
  done < <(
    {
      git diff --name-only
      git diff --cached --name-only
      git ls-files --others --exclude-standard
    } | sort -u
  )
fi

if [ "${#js_targets[@]}" -gt 0 ]; then
  step "node --check（${#js_targets[@]} 个 JS）"
  if command -v node >/dev/null 2>&1; then
    for path in "${js_targets[@]}"; do
      node --check "$path" || failed=1
    done
  else
    echo "跳过：未找到 node"
  fi
fi

if [ "$run_all" = "1" ]; then
  step "unittest（全量）"
  "$PYTHON" -m unittest discover -s tests -p 'test_*.py' || failed=1
elif [ "${#test_targets[@]}" -gt 0 ]; then
  step "unittest（${#test_targets[@]} 个用例）"
  "$PYTHON" -m unittest "${test_targets[@]}" || failed=1
else
  step "unittest"
  echo "跳过：未指定用例（用 --all 跑全量，或直接传 tests.test_xxx）"
fi

# 交接文档是「每个会话开头都要读」的文件，大了就是每个请求都重复付费。
# 预算与 scripts/rotate_handoff.py 的 DEFAULT_MAX_BYTES 保持一致（32 * 1024）。
# 只卡体积、不调 rotate_handoff.py --check：后者还看「最近 14 天」窗口，
# 长时间没写交接也会报「需要轮转」，会让本脚本无故失败。
step "handoff 体积预算"
HANDOFF_BUDGET_BYTES="${HANDOFF_BUDGET_BYTES:-32768}"
HANDOFF_PATH="docs/superpowers/handoff.md"
if [ ! -f "$HANDOFF_PATH" ]; then
  echo "跳过：未找到 $HANDOFF_PATH"
else
  handoff_bytes=$(wc -c < "$HANDOFF_PATH" | tr -d ' ')
  if [ "$handoff_bytes" -gt "$HANDOFF_BUDGET_BYTES" ]; then
    echo "✗ $HANDOFF_PATH 超出体积预算：${handoff_bytes} > ${HANDOFF_BUDGET_BYTES} 字节"
    echo "  运行 .venv/bin/python scripts/rotate_handoff.py 归档旧条目后重新验证"
    failed=1
  else
    echo "✓ $HANDOFF_PATH ${handoff_bytes} 字节（预算 ${HANDOFF_BUDGET_BYTES}）"
  fi
fi

step "git diff --check"
git diff --check || failed=1

if [ "$failed" = "0" ]; then
  printf '\n✅ check.sh 全部通过\n'
else
  printf '\n❌ check.sh 有失败项（见上方输出）\n'
fi
exit "$failed"
