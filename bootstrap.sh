#!/usr/bin/env bash
set -euo pipefail
REPO_URL="https://github.com/samtumwesigye2-create/UNG-EDGE.git"
SRC="${HOME}/ung-edge-src"

if [ -d "${SRC}/.git" ]; then
  git -C "${SRC}" fetch --depth=1 origin main
  git -C "${SRC}" reset --hard origin/main
else
  rm -rf "${SRC}"
  git clone --depth=1 "${REPO_URL}" "${SRC}"
fi

bash "${SRC}/install.sh"
