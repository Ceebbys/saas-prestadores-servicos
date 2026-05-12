#!/bin/bash
# setup_realtime.sh — Habilita Daphne (WebSocket) em paralelo ao Gunicorn.
#
# Faz UMA VEZ na VPS (~1 min). Após isso, o tempo real fica ativo
# permanentemente e os polls HTMX viram fallback se WS cair.
#
# Uso:
#   ssh saas@servidor 'cd /opt/saas-prestadores && bash deploy/setup_realtime.sh'
#
# Idempotente: pode rodar várias vezes sem efeito colateral.

set -euo pipefail

cd /opt/saas-prestadores

echo "[1/5] Validando Daphne instalado..."
if [ ! -x venv/bin/daphne ]; then
    echo "ERRO: venv/bin/daphne não encontrado. Rode pip install -r requirements/base.txt primeiro."
    exit 1
fi

echo "[2/5] Instalando systemd unit saas-daphne.service..."
sudo cp deploy/saas-daphne.service /etc/systemd/system/saas-daphne.service
sudo systemctl daemon-reload
sudo systemctl enable saas-daphne.service

echo "[3/5] Atualizando nginx para fazer proxy WS → Daphne 8002..."
sudo cp deploy/nginx-servicos.conf /etc/nginx/sites-available/servicos
sudo nginx -t

echo "[4/5] Iniciando/reiniciando saas-daphne..."
sudo systemctl restart saas-daphne.service
sleep 2
sudo systemctl is-active saas-daphne.service

echo "[5/5] Reload nginx..."
sudo systemctl reload nginx

echo
echo "✅ Setup completo."
echo
echo "Verificações:"
echo "  systemctl status saas-daphne     # serviço rodando"
echo "  curl -i https://servicos.cebs-server.cloud/ws/inbox/  # deve dar 4xx (não 502)"
echo
echo "Logs Daphne:"
echo "  journalctl -u saas-daphne -f"
