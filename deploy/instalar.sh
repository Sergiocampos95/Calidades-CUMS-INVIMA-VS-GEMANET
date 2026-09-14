#!/usr/bin/env bash
# Instala y arranca los dos servicios de Calidades CUMS para ESTE usuario
# (systemd --user). Toma GEMANET_DB_DSN del shell actual (exportala antes) y
# genera SECRET_KEY. Idempotente: no pisa un env existente.
#
#   export GEMANET_DB_DSN='postgresql://...'   # o ya en ~/.bashrc
#   deploy/instalar.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/gemanet_cums"
ENV_FILE="$CONF/env"
UNITS="$HOME/.config/systemd/user"
LISTADOS="${INVIMA_LISTADOS_DIR:-$HOME/gemanet/invima}"

mkdir -p "$CONF" "$UNITS" "$LISTADOS"
if [[ ! -f "$ENV_FILE" ]]; then
  : "${GEMANET_DB_DSN:?Exporta GEMANET_DB_DSN antes de correr este script}"
  umask 077
  {
    echo "GEMANET_DB_DSN=$GEMANET_DB_DSN"
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    echo "INVIMA_LISTADOS_DIR=$LISTADOS"
    echo "MAX_INTENTOS=5"
    echo "BLOQUEO_MINUTOS=15"
    echo "SESION_HORAS=8"
  } > "$ENV_FILE"
  echo "Creado $ENV_FILE"
else
  echo "Ya existe $ENV_FILE (no se toca)"
fi

if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "Falta $REPO/.venv: crearlo con 'python3 -m venv --without-pip .venv' y 'pip3 --python .venv/bin/python install -e .[dev]'" >&2
  exit 1
fi
if [[ ! -f "$REPO/frontend/dist/index.html" ]]; then
  echo "Aviso: no existe frontend/dist -- la API arranca pero no sirve la pantalla. Compilar con: cd frontend && npm run build" >&2
fi

cp "$REPO/deploy/gemanet-cums-api.service" "$REPO/deploy/gemanet-cums-worker.service" "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable --now gemanet-cums-worker.service gemanet-cums-api.service
systemctl --user --no-pager --lines=0 status gemanet-cums-worker.service gemanet-cums-api.service || true
echo
echo "Listados de INVIMA: dejar los 4 .xlsx en $LISTADOS"
echo "Logs: journalctl --user -u gemanet-cums-api -f   (o -u gemanet-cums-worker)"
echo "Reiniciar tras un cambio: systemctl --user restart gemanet-cums-api gemanet-cums-worker"
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
  echo "Para que arranquen al reiniciar la maquina sin abrir sesion, una sola vez:"
  echo "    sudo loginctl enable-linger $USER"
fi
