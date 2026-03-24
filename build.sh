#!/usr/bin/env bash
# Build script for Render deployment
set -o errexit

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements/base.txt

echo "==> Installing Tailwind CSS CLI..."
TAILWIND_VERSION="v4.1.8"
curl -sLO "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64"
chmod +x tailwindcss-linux-x64

echo "==> Compiling CSS..."
./tailwindcss-linux-x64 -i src/css/input.css -o static/css/output.css --minify

echo "==> Running migrations..."
python manage.py migrate --noinput

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Seeding demo data (skips if already exists)..."
python manage.py seed_demo_data || true

echo "==> Build complete!"
