#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/node/Auto-Recycle-Dialer"
SERVICE_NAME="credtu-dialer.service"

cd "$PROJECT_DIR"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m py_compile   src/application/main.py   src/service/credtu_automation.py   src/service/driver_service.py

sudo cp deploy/credtu-dialer.service "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2

sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
curl -s http://127.0.0.1:6777/health || true
echo
