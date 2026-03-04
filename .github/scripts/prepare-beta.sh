#!/usr/bin/env bash
set -euo pipefail
trap 'echo "ERROR: prepare-beta.sh 在第 $LINENO 行失败，退出码 $?" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
source "$ROOT/.github/scripts/versionmd.sh"

VERSION_FILE="$ROOT/VERSION.md"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "缺少 VERSION.md，无法执行 beta 发布。" >&2
  exit 1
fi

version="$(parse_version "$VERSION_FILE")"

current_entries_file=""
previous_entries_file=""
previous_version_file=""
cleanup_temp_files() {
  [[ -n "${current_entries_file:-}" ]] && rm -f "$current_entries_file" || true
  [[ -n "${previous_entries_file:-}" ]] && rm -f "$previous_entries_file" || true
  [[ -n "${previous_version_file:-}" ]] && rm -f "$previous_version_file" || true
}
trap cleanup_temp_files EXIT

mapfile -t valid_tags < <(git tag -l "v${version}-beta.*" | grep -E "^v${version}-beta\.[0-9]+$" | sort -V || true)
head_tag="$(git tag --points-at HEAD | grep -E "^v${version}-beta\.[0-9]+$" | sort -V | tail -n 1 || true)"

tag=""
create_tag="true"
previous_tag=""

if [[ -n "$head_tag" ]]; then
  tag="$head_tag"
  create_tag="false"

  for existing_tag in "${valid_tags[@]}"; do
    if [[ "$existing_tag" == "$tag" ]]; then
      break
    fi
    previous_tag="$existing_tag"
  done
else
  if ((${#valid_tags[@]} > 0)); then
    previous_tag="${valid_tags[${#valid_tags[@]} - 1]}"
    next_number="${previous_tag##*.}"
    next_number="$((next_number + 1))"
  else
    next_number="1"
  fi

  tag="v${version}-beta.${next_number}"
fi

current_entries_file="$(mktemp)"
extract_entries "$VERSION_FILE" "$current_entries_file"

previous_entries_file="$(mktemp)"
: > "$previous_entries_file"
if [[ -n "$previous_tag" ]] && git cat-file -e "${previous_tag}:VERSION.md" 2>/dev/null; then
  previous_version_file="$(mktemp)"
  git show "${previous_tag}:VERSION.md" > "$previous_version_file"
  extract_entries "$previous_version_file" "$previous_entries_file"
fi

delta_entries_file="$ROOT/release-notes/${tag}.entries.txt"
mkdir -p "$ROOT/release-notes"
multiset_subtract "$current_entries_file" "$previous_entries_file" "$delta_entries_file"

notes_file="$ROOT/release-notes/${tag}.md"
write_notes "$delta_entries_file" "$notes_file" "相较于上一个 beta 版本无新增条目，本次仅包含代码变更。"

{
  echo "tag=$tag"
  echo "pack_version=${tag#v}"
  echo "create_tag=$create_tag"
  echo "previous_tag=$previous_tag"
} >> "$GITHUB_OUTPUT"
