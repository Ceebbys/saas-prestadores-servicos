#!/usr/bin/env bash
# RV06 — Instala Node.js 20 LTS na VPS (idempotente).
#
# Uso: bash install_node.sh (executar localmente é seguro também, só vai pular)
#       OU
#       python deploy/ssh_exec.py "bash /opt/saas-prestadores/install_node.sh"

set -euo pipefail

REQUIRED_MAJOR=20

if command -v node >/dev/null 2>&1; then
    CURRENT=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [ "$CURRENT" -ge "$REQUIRED_MAJOR" ]; then
        echo "[install_node] Node já instalado: $(node --version) (>= ${REQUIRED_MAJOR}). Pulando."
        exit 0
    fi
    echo "[install_node] Node $(node --version) é mais antigo que ${REQUIRED_MAJOR}.x. Atualizando..."
fi

# Detecta sistema operacional
if [ ! -f /etc/os-release ]; then
    echo "[install_node] Sistema operacional não detectado (/etc/os-release ausente)."
    exit 1
fi

. /etc/os-release

case "$ID" in
    debian|ubuntu)
        echo "[install_node] Instalando Node ${REQUIRED_MAJOR}.x via NodeSource em ${PRETTY_NAME}..."
        curl -fsSL "https://deb.nodesource.com/setup_${REQUIRED_MAJOR}.x" | sudo -E bash -
        sudo apt-get install -y nodejs
        ;;
    centos|rhel|rocky|almalinux)
        echo "[install_node] Instalando Node ${REQUIRED_MAJOR}.x via NodeSource em ${PRETTY_NAME}..."
        curl -fsSL "https://rpm.nodesource.com/setup_${REQUIRED_MAJOR}.x" | sudo -E bash -
        sudo yum install -y nodejs
        ;;
    *)
        echo "[install_node] Distribuição ${ID} não suportada. Instale Node ${REQUIRED_MAJOR}.x manualmente."
        exit 1
        ;;
esac

echo "[install_node] OK — versão final: $(node --version) / npm $(npm --version)"
