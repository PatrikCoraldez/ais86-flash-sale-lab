set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
docker compose --profile share up -d tunnel
printf '%s\n' 'Copia la URL HTTPS del registro. Para cerrar el acceso: docker compose stop tunnel.'
docker compose logs -f tunnel
