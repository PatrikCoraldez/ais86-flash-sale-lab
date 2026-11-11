import argparse
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--path", default=".env")
args = parser.parse_args()
path = Path(args.path)
if path.exists():
    print("Configuración existente conservada.")
else:
    content = "\n".join(["POSTGRES_PASSWORD=" + secrets.token_hex(32), "REDIS_PASSWORD=" + secrets.token_hex(32), "LAB_KEY=" + secrets.token_hex(32), "FLASH_PORT=8019", ""])
    with path.open("x", encoding="utf-8") as f:
        f.write(content)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print("Configuración local creada. LAB_KEY está en .env; compártela solo por un canal privado con tu docente.")
