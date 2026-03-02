#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "用法: cleanup-dev.sh <released-entries-file> <released-version>" >&2
  exit 1
fi

released_entries_file="$1"
released_version="$2"

ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
source "$ROOT/.github/scripts/versionmd.sh"

if [[ ! -f "$released_entries_file" ]]; then
  echo "找不到已发布条目文件: $released_entries_file" >&2
  exit 1
fi

if [[ ! -s "$released_entries_file" ]]; then
  echo "已发布条目为空，跳过 dev 清理。"
  exit 0
fi

git fetch origin dev --tags
git checkout dev
git pull --ff-only origin dev

if [[ ! -f VERSION.md ]]; then
  echo "dev 分支缺少 VERSION.md，无法清理。" >&2
  exit 1
fi

dev_version="$(parse_version VERSION.md)"
dev_entries_file="$(mktemp)"
extract_entries VERSION.md "$dev_entries_file"

remaining_entries_file="$(mktemp)"
multiset_subtract "$dev_entries_file" "$released_entries_file" "$remaining_entries_file"

if cmp -s "$dev_entries_file" "$remaining_entries_file"; then
  echo "dev 分支没有可清理的已发布条目。"
  exit 0
fi

write_versionmd VERSION.md "$dev_version" "$remaining_entries_file"

if git diff --quiet -- VERSION.md; then
  echo "VERSION.md 无变更，跳过提交。"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add VERSION.md
git commit -m "chore: 清理已发布版本说明 (v${released_version})"
git push origin dev
