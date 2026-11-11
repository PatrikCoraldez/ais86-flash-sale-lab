import uuid
from datetime import datetime, timezone

from app.events import validate_cloud_event


def complete_event() -> dict:
    return {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": "/services/orders",
        "type": "pe.unamba.flash.order.created.v1",
        "time": datetime.now(timezone.utc).isoformat(),
        "datacontenttype": "application/json",
        "data": {
            "order_id": str(uuid.uuid4()),
            "items": [
                {"product_id": "nova-headphones", "quantity": 2},
                {"product_id": "arc-mouse", "quantity": 1},
            ],
            "total_cents": 309700,
        },
    }


def test_valid_event_passes() -> None:
    assert validate_cloud_event(complete_event()) == []


def test_event_requires_identity_fields() -> None:
    event = complete_event()
    event["id"] = "not-a-uuid"
    event["source"] = "elsewhere"
    event["type"] = "wrong.type"
    errors = validate_cloud_event(event)
    assert any("id" in error for error in errors)
    assert any("source" in error for error in errors)
    assert any("type" in error for error in errors)


def test_event_requires_items_and_integer_quantities() -> None:
    event = complete_event()
    event["data"]["items"] = [{"product_id": "nova-headphones", "quantity": "2"}]
    assert any("quantity" in error for error in validate_cloud_event(event))

    event["data"]["items"] = [{"product_id": "nova-headphones", "quantity": True}]
    assert any("quantity" in error for error in validate_cloud_event(event))

    event["data"]["items"] = []
    assert any("items" in error for error in validate_cloud_event(event))


def test_event_requires_non_negative_total() -> None:
    event = complete_event()
    event["data"]["total_cents"] = -1
    assert any("total_cents" in error for error in validate_cloud_event(event))

    event["data"]["total_cents"] = "100"
    assert any("total_cents" in error for error in validate_cloud_event(event))
