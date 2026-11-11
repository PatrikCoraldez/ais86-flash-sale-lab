import os
import uuid

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get("FLASH_TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("FLASH_TEST_REDIS_URL")
TEST_LAB_KEY = os.environ.get("FLASH_TEST_LAB_KEY", "integration-lab-key-" + "k" * 32)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or not TEST_REDIS_URL,
    reason="requires FLASH_TEST_DATABASE_URL and FLASH_TEST_REDIS_URL",
)


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["REDIS_URL"] = TEST_REDIS_URL
    os.environ["LAB_KEY"] = TEST_LAB_KEY
    os.environ["FRONTEND_DIST"] = os.path.join(os.path.dirname(__file__), "missing-dist")
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def lab_headers(run_id: str | None = None) -> dict[str, str]:
    headers = {"X-Lab-Key": TEST_LAB_KEY}
    if run_id is not None:
        headers["X-Lab-Run"] = run_id
    return headers


def create_run(client: TestClient, stock: int = 5, delay: int = 0) -> str:
    response = client.post(
        "/_lab/runs",
        json={"stock": stock, "notification_delay_ms": delay},
        headers=lab_headers(),
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def test_health_and_headers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "flash-sale"
    assert body["protocol"] == "ais86.s09.v1"
    assert isinstance(body["instance_id"], str) and body["instance_id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers


def test_public_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    body = response.json()
    assert body["campaign"]["currency"] == "PEN"
    assert len(body["items"]) == 6
    identifiers = {item["id"] for item in body["items"]}
    assert identifiers == {
        "nova-headphones",
        "orbit-keyboard",
        "pulse-speaker",
        "arc-mouse",
        "terra-pack",
        "flux-hub",
    }
    for item in body["items"]:
        assert item["image"] == f"/assets/{item['id']}.svg"
        assert item["price_cents"] <= item["original_price_cents"]
        assert item["stock"] >= 0


def test_lab_authentication(client: TestClient) -> None:
    assert client.get("/_lab/runs/" + str(uuid.uuid4())).status_code == 401
    assert (
        client.get(
            "/_lab/runs/" + str(uuid.uuid4()),
            headers={"X-Lab-Key": "wrong-key-" + "x" * 40},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/products", headers={"X-Lab-Run": str(uuid.uuid4())}).status_code == 401
    assert (
        client.get(
            "/api/v1/products",
            headers=lab_headers(str(uuid.uuid4())),
        ).status_code
        == 404
    )


def test_order_lifecycle_and_idempotency(client: TestClient) -> None:
    run_id = create_run(client, stock=5)
    headers = {**lab_headers(run_id), "Idempotency-Key": "order-key-0001"}
    body = {"items": [{"product_id": "nova-headphones", "quantity": 2}]}

    first = client.post("/api/v1/orders", json=body, headers=headers)
    assert first.status_code == 201
    created = first.json()
    assert created["status"] == "confirmed"
    assert created["notification_status"] == "pending"
    assert created["total_cents"] == 259800
    assert first.headers["location"] == f"/api/v1/orders/{created['id']}"

    replay = client.post("/api/v1/orders", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json() == created

    conflict = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "nova-headphones", "quantity": 1}]},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    fetched = client.get(f"/api/v1/orders/{created['id']}", headers=lab_headers(run_id))
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["id"] == created["id"]
    assert fetched_body["total_cents"] == created["total_cents"]
    assert fetched_body["notification_status"] in {"pending", "sent", "failed"}

    assert client.get(f"/api/v1/orders/{created['id']}").status_code == 404

    run_state = client.get(f"/_lab/runs/{run_id}", headers=lab_headers())
    assert run_state.status_code == 200
    state = run_state.json()
    assert state["run_id"] == run_id
    assert len(state["products"]) == 6
    assert any(order["id"] == created["id"] for order in state["orders"])
    assert "X-Lab-Key" not in str(state)
    assert "idempotency" not in str(state).lower()

    assert client.delete(f"/_lab/runs/{run_id}", headers=lab_headers()).status_code == 204
    assert client.get(f"/_lab/runs/{run_id}", headers=lab_headers()).status_code == 404


def test_order_validation_and_stock(client: TestClient) -> None:
    run_id = create_run(client, stock=1)
    headers = {**lab_headers(run_id), "Idempotency-Key": "order-key-0002"}

    for items in (
        [],
        [{"product_id": "nova-headphones", "quantity": 0}],
        [{"product_id": "nova-headphones", "quantity": 6}],
        [{"product_id": "a" * 65, "quantity": 1}],
        [
            {"product_id": "nova-headphones", "quantity": 1},
            {"product_id": "nova-headphones", "quantity": 1},
        ],
        [{"product_id": f"product-{index}", "quantity": 1} for index in range(7)],
    ):
        response = client.post("/api/v1/orders", json={"items": items}, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_product = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "missing-product", "quantity": 1}]},
        headers=headers,
    )
    assert missing_product.status_code == 404
    assert missing_product.json()["error"]["code"] == "NOT_FOUND"

    missing_key = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "nova-headphones", "quantity": 1}]},
        headers=lab_headers(run_id),
    )
    assert missing_key.status_code == 422

    out_of_stock = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "nova-headphones", "quantity": 2}]},
        headers=headers,
    )
    assert out_of_stock.status_code == 409
    assert out_of_stock.json()["error"]["code"] == "OUT_OF_STOCK"

    catalog = client.get("/api/v1/products", headers=lab_headers(run_id)).json()
    stocks = {item["id"]: item["stock"] for item in catalog["items"]}
    assert stocks["nova-headphones"] == 1

    assert client.delete(f"/_lab/runs/{run_id}", headers=lab_headers()).status_code == 204


def test_run_isolation(client: TestClient) -> None:
    first_run = create_run(client, stock=4)
    second_run = create_run(client, stock=4)
    headers = {**lab_headers(first_run), "Idempotency-Key": "order-key-0003"}
    created = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": "arc-mouse", "quantity": 1}]},
        headers=headers,
    )
    assert created.status_code == 201
    order_id = created.json()["id"]

    assert (
        client.get(f"/api/v1/orders/{order_id}", headers=lab_headers(second_run)).status_code
        == 404
    )
    second_catalog = client.get("/api/v1/products", headers=lab_headers(second_run)).json()
    assert all(item["stock"] == 4 for item in second_catalog["items"])
    first_catalog = client.get("/api/v1/products", headers=lab_headers(first_run)).json()
    first_stocks = {item["id"]: item["stock"] for item in first_catalog["items"]}
    assert first_stocks["arc-mouse"] == 3

    assert client.delete(f"/_lab/runs/{first_run}", headers=lab_headers()).status_code == 204
    assert client.delete(f"/_lab/runs/{second_run}", headers=lab_headers()).status_code == 204


def test_body_limit(client: TestClient) -> None:
    response = client.post(
        "/_lab/runs",
        content=b'{"stock":50,"notification_delay_ms":0,"padding":"' + b"x" * 20000 + b'"}',
        headers={**lab_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
