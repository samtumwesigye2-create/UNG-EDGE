#!/usr/bin/env bash
set -euo pipefail
EDGE_HOME="${HOME}/ung-edge"
VENV="${EDGE_HOME}/venv"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${EDGE_HOME}/data"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -r "${SRC_DIR}/requirements.txt"
cp "${SRC_DIR}/app.py" "${EDGE_HOME}/app.py"
cp "${SRC_DIR}/atlas_client.py" "${EDGE_HOME}/atlas_client.py"

ENV_FILE="${EDGE_HOME}/edge.env"
touch "${ENV_FILE}"
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}
set_env UNG_EDGE_NODE_ID ung-edge-001
set_env UNG_EDGE_DATA_DIR "${EDGE_HOME}/data"
set_env UNG_EDGE_SYNC_INTERVAL_SECONDS 15
set_env UNG_EDGE_HEARTBEAT_SECONDS 30
set_env UNG_EDGE_ROLE field-gateway
set_env UNG_NEXUS_URL https://ung-nexus-production.up.railway.app
set_env UNG_PULSAR_URL https://ung-pulsar-production.up.railway.app
set_env UNG_ATLAS_URL https://ung-atlas-production.up.railway.app
# Preserve an existing secret if one has already been provisioned. Never write secrets from source control.
if ! grep -q '^UNG_EDGE_SERVICE_TOKEN=' "${ENV_FILE}"; then printf '%s\n' 'UNG_EDGE_SERVICE_TOKEN=' >> "${ENV_FILE}"; fi

sudo tee /etc/systemd/system/ung-edge.service >/dev/null <<EOF
[Unit]
Description=UNG-EDGE Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${EDGE_HOME}
EnvironmentFile=${ENV_FILE}
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

for i in $(seq 1 25); do
  if curl -fsS http://127.0.0.1:8080/health; then
    echo
    echo "=== UNG-EDGE-001 ONLINE ==="
    echo "Control Center: http://$(hostname -I | awk '{print $1}'):8080/control"
    exit 0
  fi
  sleep 1
done

echo "=== UNG-EDGE STARTUP FAILED ===" >&2
sudo systemctl status ung-edge.service --no-pager -l || true
sudo journalctl -u ung-edge.service -n 80 --no-pager || true
exit 1
