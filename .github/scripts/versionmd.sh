#!/usr/bin/env bash
set -euo pipefail

readonly VERSIONMD_SECTIONS=("新增" "变更" "修复" "其他")

parse_version() {
  local file_path="$1"
  local version_line
  version_line="$(grep -E '^Version:[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+[[:space:]]*$' "$file_path" | head -n 1 || true)"
  if [[ -z "$version_line" ]]; then
    echo "未在 $file_path 找到合法的 Version: X.Y.Z 行。" >&2
    return 1
  fi

  echo "$version_line" | sed -E 's/^Version:[[:space:]]*//; s/[[:space:]]*$//'
}

extract_entries() {
  local file_path="$1"
  local output_file="$2"
  local in_unreleased="false"
  local current_section=""

  : > "$output_file"

  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    local line
    line="$(printf '%s' "$raw_line" | sed -E 's/[[:space:]]+$//')"

    if [[ "$line" =~ ^##[[:space:]]+待发布[[:space:]]*$ ]]; then
      in_unreleased="true"
      current_section=""
      continue
    fi

    if [[ "$line" =~ ^##[[:space:]]+ ]] && [[ "$line" != "## 待发布" ]]; then
      in_unreleased="false"
      current_section=""
      continue
    fi

    if [[ "$in_unreleased" != "true" ]]; then
      continue
    fi

    if [[ "$line" == "### "* ]]; then
      current_section=""
      local section
      for section in "${VERSIONMD_SECTIONS[@]}"; do
        if [[ "$line" == "### $section" ]]; then
          current_section="$section"
          break
        fi
      done
      continue
    fi

    if [[ "$line" == "- "* ]] && [[ -n "$current_section" ]]; then
      local item
      item="${line#- }"
      if [[ -n "$item" ]]; then
        printf '%s\t%s\n' "$current_section" "$item" >> "$output_file"
      fi
    fi
  done < "$file_path"
}

multiset_subtract() {
  local base_file="$1"
  local remove_file="$2"
  local output_file="$3"

  if [[ ! -f "$remove_file" ]]; then
    cp "$base_file" "$output_file"
    return 0
  fi

  awk '
    NR == FNR { counts[$0]++; next }
    {
      if (counts[$0] > 0) {
        counts[$0]--
      } else {
        print $0
      }
    }
  ' "$remove_file" "$base_file" > "$output_file"
}

write_notes() {
  local entries_file="$1"
  local output_file="$2"
  local empty_message="${3:-无新增版本说明，发布仅包含代码变更。}"

  if [[ ! -s "$entries_file" ]]; then
    {
      echo "## 更新内容"
      echo
      echo "- $empty_message"
    } > "$output_file"
    return 0
  fi

  {
    echo "## 更新内容"

    local section
    for section in "${VERSIONMD_SECTIONS[@]}"; do
      mapfile -t section_items < <(awk -F '\t' -v target="$section" '$1 == target { print $2 }' "$entries_file")
      if ((${#section_items[@]} == 0)); then
        continue
      fi

      echo
      echo "### $section"
      local item
      for item in "${section_items[@]}"; do
        echo "- $item"
      done
    done
  } > "$output_file"
}

write_versionmd() {
  local output_file="$1"
  local version="$2"
  local entries_file="$3"

  {
    echo "# PrismCore 版本信息"
    echo
    echo "Version: $version"
    echo
    echo "## 待发布"
    echo

    local section
    for section in "${VERSIONMD_SECTIONS[@]}"; do
      echo "### $section"
      awk -F '\t' -v target="$section" '$1 == target { print "- " $2 }' "$entries_file"
      echo
    done
  } > "$output_file"
}
