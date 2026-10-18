#!/usr/bin/env bash
# video-publish-prep 一键安装脚本（macOS / Linux）
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="${HOME}/.workbuddy/skills/video-publish-prep"

echo ""
echo "  video-publish-prep  Installer"
echo "  ----------------------------------------"
echo "  Source : ${SRC}"
echo "  Target : ${DST}"
echo ""

if [[ ! -f "${SRC}/SKILL.md" ]]; then
  echo "  [ERROR] SKILL.md not found. Run this script inside the skill folder."
  exit 1
fi

mkdir -p "${DST}"

# 用 rsync（有则用，排除私密文件），否则退回 cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude='__pycache__/' \
    --exclude='.video-publish/' \
    --exclude='config.json' \
    --exclude='*.pyc' \
    "${SRC}/" "${DST}/"
else
  ( cd "${SRC}" && tar --exclude='__pycache__' --exclude='.video-publish' \
      --exclude='config.json' --exclude='*.pyc' -cf - . ) | ( cd "${DST}" && tar -xf - )
fi

chmod +x "${DST}/scripts/"*.py 2>/dev/null || true

echo "  [OK] Installed to:"
echo "       ${DST}"
echo ""
echo "  Next steps:"
echo "    1. Restart your agent client to load the skill."
echo "    2. Optional: set Agnes API Key (only needed for --ai-color)"
echo "         export AGNES_API_KEY=\"sk-xxxx\""
echo "       or edit ${DST}/config.json"
echo ""
echo "  Quick try:"
echo "    python3 \"${DST}/scripts/quick.py\" --headline \"Hello\" --subheadline \"World\" --tone tech"
echo ""
