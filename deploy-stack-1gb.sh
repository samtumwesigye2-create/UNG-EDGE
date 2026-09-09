#!/usr/bin/env bash
set -u

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo bash deploy-stack-1gb.sh"
  exit 1
fi

OWNER="samtumwesigye2-create"
BASE="/opt/ung-stack"
REPORT="/var/log/ung-stack-1gb-report.txt"
mkdir -p "$BASE"
: > "$REPORT"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 python3-venv python3-pip curl

# 1GB edge profile: keep UNG-EDGE on 8080 and add four lightweight local services.
SERVICES=(
  "UNG-CORE:8101"
  "UNG-NEXUS:8102"
  "UNG-ATLAS:8104"
  "UNG-ORACLE:8113"
)

sanitize() {
  echo "$1" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-'
}

pick_start() {
  local dir="$1" port="$2" cmd=""
  if [ -f "$dir/Procfile" ]; then
    cmd="$(sed -n 's/^web:[[:space:]]*//p' "$dir/Procfile" | head -n1)"
    cmd="${cmd//\$\{PORT:-8000\}/$port}"
    cmd="${cmd//\$\{PORT\}/$port}"
    cmd="${cmd//\$PORT/$port}"
  fi
  if [ -z "$cmd" ] && [ -f "$dir/entrypoint.py" ]; then cmd="python -m uvicorn entrypoint:app --host 0.0.0.0 --port $port"; fi
  if [ -z "$cmd" ] && [ -f "$dir/app/main.py" ]; then cmd="python -m uvicorn app.main:app --host 0.0.0.0 --port $port"; fi
  if [ -z "$cmd" ] && [ -f "$dir/main.py" ]; then cmd="python -m uvicorn main:app --host 0.0.0.0 --port $port"; fi
  if [ -z "$cmd" ] && [ -f "$dir/app.py" ]; then cmd="python -m uvicorn app:app --host 0.0.0.0 --port $port"; fi
  echo "$cmd"
}

for item in "${SERVICES[@]}"; do
  repo="${item%%:*}"
  port="${item##*:}"
  unit="$(sanitize "$repo")-local"
  dir="$BASE/$repo"

  echo "===== $repo : $port =====" | tee -a "$REPORT"
  if [ -d "$dir/.git" ]; then
    git -C "$dir" fetch --depth 1 origin main >>"$REPORT" 2>&1 || true
    git -C "$dir" reset --hard origin/main >>"$REPORT" 2>&1 || true
  else
    rm -rf "$dir"
    if ! git clone --depth 1 "https://github.com/$OWNER/$repo.git" "$dir" >>"$REPORT" 2>&1; then
      echo "$repo CLONE_FAILED" | tee -a "$REPORT"
      continue
    fi
  fi

  if [ ! -f "$dir/requirements.txt" ]; then
    echo "$repo CODE_ONLY no requirements.txt" | tee -a "$REPORT"
    continue
  fi

  rm -rf "$dir/venv"
  python3 -m venv "$dir/venv"
  "$dir/venv/bin/pip" install --upgrade pip wheel setuptools >>"$REPORT" 2>&1 || { echo "$repo VENV_FAILED" | tee -a "$REPORT"; continue; }
  "$dir/venv/bin/pip" install -r "$dir/requirements.txt" >>"$REPORT" 2>&1 || { echo "$repo DEPENDENCY_FAILED" | tee -a "$REPORT"; continue; }

  cmd="$(pick_start "$dir" "$port")"
  if [ -z "$cmd" ]; then
    echo "$repo CODE_ONLY no recognized API entrypoint" | tee -a "$REPORT"
    continue
  fi

  cat > "/etc/systemd/system/${unit}.service" <<EOF
[Unit]
Description=$repo local 1GB edge-profile service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$dir
Environment=PORT=$port
Environment=PATH=$dir/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/bin/bash -lc '$cmd'
Restart=on-failure
RestartSec=3
MemoryHigh=140M
MemoryMax=180M
CPUQuota=80%
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

done

systemctl daemon-reload
for item in "${SERVICES[@]}"; do
  repo="${item%%:*}"
  unit="$(sanitize "$repo")-local"
  systemctl enable "$unit" >/dev/null 2>&1 || true
  systemctl restart "$unit" >/dev/null 2>&1 || true
done

sleep 5

echo "===== SERVICE STATUS =====" | tee -a "$REPORT"
for item in "${SERVICES[@]}"; do
  repo="${item%%:*}"
  port="${item##*:}"
  unit="$(sanitize "$repo")-local"
  if systemctl is-active --quiet "$unit"; then
    if curl -fsS --max-time 3 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "$repo ACTIVE HEALTHY http://127.0.0.1:$port" | tee -a "$REPORT"
    else
      echo "$repo ACTIVE health-endpoint-unconfirmed http://127.0.0.1:$port" | tee -a "$REPORT"
    fi
  else
    echo "$repo FAILED_START" | tee -a "$REPORT"
    journalctl -u "$unit" -n 10 --no-pager >>"$REPORT" 2>&1 || true
  fi
done

echo "===== EXISTING EDGE =====" | tee -a "$REPORT"
systemctl is-active ung-edge 2>/dev/null | sed 's/^/UNG-EDGE /' | tee -a "$REPORT" || true
curl -fsS --max-time 3 http://127.0.0.1:8080/health 2>/dev/null | tee -a "$REPORT" || true
echo | tee -a "$REPORT"

echo "===== PI RESOURCES =====" | tee -a "$REPORT"
free -h | tee -a "$REPORT"
df -h / | tee -a "$REPORT"
if command -v vcgencmd >/dev/null 2>&1; then vcgencmd measure_temp | tee -a "$REPORT"; fi

echo "===== RUNNING UNG SERVICES =====" | tee -a "$REPORT"
systemctl list-units --type=service --state=running --no-pager | grep -E 'ung-(edge|core|nexus|atlas|oracle)' | tee -a "$REPORT" || true

echo "EDGE_1GB_PROFILE_COMPLETE"
echo "Report: $REPORT"
