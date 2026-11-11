set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -f .env ]; then
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work python:3.12-slim python tools/init_env.py
fi
docker compose up --build -d --wait
printf '%s\n' 'Tienda: http://localhost:8019 (o el FLASH_PORT configurado en .env)' 'Clave de evaluación: LAB_KEY en .env, no la publiques.'
