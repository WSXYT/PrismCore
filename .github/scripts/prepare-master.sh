#!/usr/bin/env bash
set -euo pipefail
trap 'echo "ERROR: prepare-master.sh 在第 $LINENO 行失败，退出码 $?" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
source "$ROOT/.github/scripts/versionmd.sh"

VERSION_FILE="$ROOT/VERSION.md"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "缺少 VERSION.md，无法执行正式发布。" >&2
  exit 1
fi

version="$(parse_version "$VERSION_FILE")"
tag="v${version}"

publish="true"
create_tag="true"

if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  existing_commit="$(git rev-list -n 1 "$tag")"
  current_commit="$(git rev-parse HEAD)"

  if [[ "$existing_commit" == "$current_commit" ]]; then
    create_tag="false"
  else
    publish="false"
    create_tag="false"
    echo "标签 $tag 已存在且不指向当前提交，跳过正式发布。"
  fi
fi

mkdir -p "$ROOT/release-notes"
entries_file="$ROOT/release-notes/${tag}.entries.txt"
extract_entries "$VERSION_FILE" "$entries_file"

notes_file="$ROOT/release-notes/${tag}.md"
write_notes "$entries_file" "$notes_file" "本次发布未在 VERSION.md 中记录更新条目。"

{
  echo "publish=$publish"
  echo "create_tag=$create_tag"
  echo "tag=$tag"
  echo "pack_version=$version"
  echo "version=$version"
} >> "$GITHUB_OUTPUT"
