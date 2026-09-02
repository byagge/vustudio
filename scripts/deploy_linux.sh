#!/usr/bin/env bash
# Деплой VU Studio на Linux VPS (API + бот + portrait-api)
# Использование на сервере:
#   cd /opt/otris
#   cp .env.example .env   # заполните BOT_TOKEN, ALLOWED_USERS
#   bash scripts/deploy_linux.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Проверка Docker..."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден. Установите: https://docs.docker.com/engine/install/ubuntu/"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin не найден."
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Создайте .env из .env.example и заполните BOT_TOKEN, ALLOWED_USERS"
  exit 1
fi

mkdir -p queue output queue/pending queue/processing queue/done queue/failed

echo "==> Сборка и запуск контейнеров..."
docker compose up -d --build api portrait-api bot

echo ""
echo "Готово."
echo "  Панель:  http://$(hostname -I | awk '{print $1}'):8080"
echo "  API docs: http://$(hostname -I | awk '{print $1}'):8080/docs"
echo ""
echo "Отрисовка (Photoshop) — только на Windows с worker:"
echo "  .\\scripts\\start_render_worker.ps1"
echo "  Нужна общая папка queue/ и output/ между VPS и Windows (SMB/NFS)."
