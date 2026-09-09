#!/usr/bin/env bash
set -euo pipefail
EDGE_HOME="${HOME}/ung-edge"
VENV="${EDGE_HOME}/venv"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${EDGE_HOME}/data"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -r "${SRC_DIR}/requirements.txt"
cp "${SRC_DIR}/app.py" "${EDGE_HOME}/app.py"

if [ ! -f "${EDGE_HOME}/edge.env" ]; then
cat > "${EDGE_HOME}/edge.env" <<EOF
UNG_EDGE_NODE_ID=ung-edge-001
UNG_EDGE_DATA_DIR=${EDGE_HOME}/data
UNG_EDGE_SYNC_INTERVAL_SECONDS=15
UNG_NEXUS_URL=
UNG_PULSAR_URL=https://ung-pulsar-production.up.railway.app
UNG_EDGE_SERVICE_TOKEN=
EOF
fi

sudo tee /etc/systemd/system/ung-edge.service >/dev/null <<EOF
[Unit]
Description=UNG-EDGE Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${EDGE_HOME}
EnvironmentFile=${EDGE_HOME}/edge.env
ExecStart=${VENV}/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ung-edge.service >/dev/null
sudo systemctl restart ung-edge.service

for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8080/health; then
    echo
    echo "=== UNG-EDGE-001 ONLINE ==="
    exit 0
  fi
  sleep 1
done

echo "=== UNG-EDGE STARTUP FAILED ===" >&2
sudo systemctl status ung-edge.service --no-pager -l || true
sudo journalctl -u ung-edge.service -n 80 --no-pager || true
exit 1
