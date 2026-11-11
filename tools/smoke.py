import argparse
import json
import os
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--target", default="http://127.0.0.1:8000")
args = parser.parse_args()
base = args.target.rstrip("/")
key = os.environ.get("LAB_KEY", "")
if not key:
    sys.exit("Falta LAB_KEY. Ejecuta esta prueba con docker compose exec api python /app/tools/smoke.py")
checks = []

def request(method, path, body=None, run=None, authenticated=True, idem=None):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["X-Lab-Key"] = key
    if run:
        headers["X-Lab-Run"] = run
    if idem:
        headers["Idempotency-Key"] = idem
    raw = None if body is None else json.dumps(body).encode()
    try:
        with urlopen(Request(base + path, data=raw, headers=headers, method=method), timeout=8) as response:
            status = response.status
            content = response.read(1024 * 1024)
    except HTTPError as exc:
        status, content = exc.code, exc.read(1024 * 1024)
    return status, json.loads(content) if content else {}

def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    print("PASA | " + label)

run = None
try:
    status, health = request("GET", "/healthz", authenticated=False)
    check(status == 200 and health["protocol"] == "ais86.s09.v1", "API disponible")
    status, _ = request("POST", "/_lab/runs", {"stock": 10}, authenticated=False)
    check(status == 401, "Control docente protegido")
    status, data = request("POST", "/_lab/runs", {"stock": 10, "notification_delay_ms": 0})
    check(status == 201, "Dataset de prueba aislado")
    run = data["run_id"]
    status, catalog = request("GET", "/api/v1/products", run=run)
    check(status == 200 and len(catalog["items"]) == 6, "Catálogo disponible")
    product = catalog["items"][0]
    body = {"items": [{"product_id": product["id"], "quantity": 1}]}
    idem = uuid.uuid4().hex
    status, order = request("POST", "/api/v1/orders", body, run, idem=idem)
    check(status == 201 and order["total_cents"] == product["price_cents"], "Compra y precio calculados por API")
    status, again = request("POST", "/api/v1/orders", body, run, idem=idem)
    check(status == 201 and again == order, "Reintento sin duplicar pedido")
    status, persisted = request("GET", "/api/v1/orders/" + order["id"], run=run)
    check(status == 200 and persisted["id"] == order["id"], "Pedido consultable")
    status, state = request("GET", "/_lab/runs/" + run)
    stock = next(p["stock"] for p in state["products"] if p["id"] == product["id"])
    check(status == 200 and stock == 9 and len(state["orders"]) == 1, "Inventario y persistencia coherentes")
    print(f"Smoke: {len(checks)}/{len(checks)}. Esto no equivale a aprobar Semana 9.")
except Exception as exc:
    print("NO PASA | " + str(exc).replace(key, "[REDACTED]"), file=sys.stderr)
    sys.exit(1)
finally:
    if run:
        try:
            request("DELETE", "/_lab/runs/" + run)
        except Exception:
            print("No se pudo limpiar el dataset; caducará automáticamente.", file=sys.stderr)
