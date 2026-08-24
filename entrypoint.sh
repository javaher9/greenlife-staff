#!/bin/sh
set -eu

echo "Waiting for PostgreSQL..."
python - <<'PY'
import os, time
import psycopg
for attempt in range(60):
    try:
        with psycopg.connect(
            dbname=os.environ.get('POSTGRES_DB', 'postgres'),
            user=os.environ.get('POSTGRES_USER', 'postgres'),
            password=os.environ.get('POSTGRES_PASSWORD', ''),
            host=os.environ.get('POSTGRES_HOST', 'db'),
            port=os.environ.get('POSTGRES_PORT', '5432'),
            connect_timeout=3,
        ):
            print('PostgreSQL is ready.')
            break
    except Exception as exc:
        if attempt == 59:
            raise
        print(f'Waiting for database ({attempt + 1}/60): {exc}')
        time.sleep(2)
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_initial_data
exec gunicorn greenlife.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --timeout 120
