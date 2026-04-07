#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE_NAME="${SERVICE_NAME:-seattle-transit-updater}"
REPO_DIR="${REPO_DIR:-${ROOT_DIR}}"
RUN_USER="${RUN_USER:-${USER}}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env.data}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_DIR}/.venv/bin/python}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service-name)
      SERVICE_NAME="$2"
      UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
      shift 2
      ;;
    --repo-dir)
      REPO_DIR="$2"
      shift 2
      ;;
    --run-user)
      RUN_USER="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/install_rpi_updater_service.sh [options]

Options:
  --service-name <name>   systemd service name (default: seattle-transit-updater)
  --repo-dir <path>       repository root path
  --run-user <user>       Linux user running updater
  --env-file <path>       .env.data path passed to updater
  --python-bin <path>     Python interpreter path (usually .venv/bin/python)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  echo "Create a virtual environment first, then install requirements." >&2
  exit 1
fi

if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Repository directory not found: ${REPO_DIR}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Warning: env file not found: ${ENV_FILE}" >&2
  echo "The service will still start, but API-key-based jobs may fail." >&2
fi

TMP_UNIT="$(mktemp)"

cat > "${TMP_UNIT}" <<EOF
[Unit]
Description=Seattle Transit Continuous Data Updater
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PYTHON_BIN} scripts/continuous_data_updater.py --env-file ${ENV_FILE}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "Installing unit: ${UNIT_FILE}"
sudo install -m 644 "${TMP_UNIT}" "${UNIT_FILE}"
rm -f "${TMP_UNIT}"

echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

echo "Service status:"
sudo systemctl --no-pager status "${SERVICE_NAME}" || true

echo
echo "Useful commands:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo systemctl stop ${SERVICE_NAME}"
