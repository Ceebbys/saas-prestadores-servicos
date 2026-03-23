#!/usr/bin/env bash
# Build script for Render deployment
set -o errexit

echo "==> Installing dependencies..."
pip install --upgrade pip
pip install -r requirements/base.txt

echo "==> Running migrations..."
python manage.py migrate --noinput

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Build complete!"
