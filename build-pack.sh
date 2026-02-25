#!/bin/bash
# PrismCore Velopack 打包脚本
# 用法: bash build-pack.sh [版本号]
# 示例: bash build-pack.sh 1.0.0

set -e

VERSION="${1:?请提供版本号，例如: bash build-pack.sh 1.0.0}"
PROJECT="PrismCore.csproj"
CONFIG="Release"
OUTPUT_DIR="Releases"
ICON="Assets/app.ico"

RIDS=("win-x64" "win-arm64" "win-x86")
PLATFORMS=("x64" "ARM64" "x86")

echo "=== PrismCore v${VERSION} 打包开始 ==="

for i in "${!RIDS[@]}"; do
  RID="${RIDS[$i]}"
  PLAT="${PLATFORMS[$i]}"
  PUBLISH_DIR="publish/${RID}"

  echo ""
  echo "--- [${RID}] 发布中 ---"
  dotnet publish "$PROJECT" \
    -c "$CONFIG" \
    -r "$RID" \
    -p:Platform="$PLAT" \
    -p:WindowsPackageType=None \
    -p:SelfContained=true \
    -p:PublishReadyToRun=true \
    --output "$PUBLISH_DIR"

  echo "--- [${RID}] 打包中 ---"
  vpk pack \
    --packId "PrismCore" \
    --packVersion "$VERSION" \
    --packDir "$PUBLISH_DIR" \
    --packTitle "PrismCore" \
    --packAuthors "WSXYT" \
    --mainExe "PrismCore.exe" \
    --icon "$ICON" \
    --outputDir "${OUTPUT_DIR}" \
    --channel "${RID}" \
    --shortcuts "Desktop,StartMenuRoot"

  echo "--- [${RID}] 完成 ---"
done

echo ""
echo "=== 打包完成 ==="
echo "产物目录: ${OUTPUT_DIR}/"
ls -lh "${OUTPUT_DIR}/"
