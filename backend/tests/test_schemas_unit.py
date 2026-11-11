import pytest
from pydantic import ValidationError

from app.schemas import LabRunCreate, OrderCreate, OrderItemIn


def test_order_create_accepts_valid_payload() -> None:
    payload = OrderCreate(
        items=[
            {"product_id": "nova-headphones", "quantity": 1},
            {"product_id": "arc-mouse", "quantity": 5},
        ]
    )
    assert len(payload.items) == 2


def test_order_item_rejects_zero_and_out_of_range() -> None:
    for quantity in (0, 6, -1):
        with pytest.raises(ValidationError):
            OrderItemIn(product_id="nova-headphones", quantity=quantity)


def test_order_item_rejects_boolean_and_float() -> None:
    for quantity in (True, 2.0):
        with pytest.raises(ValidationError):
            OrderItemIn(product_id="nova-headphones", quantity=quantity)


def test_order_create_rejects_duplicate_products() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(
            items=[
                {"product_id": "nova-headphones", "quantity": 1},
                {"product_id": "nova-headphones", "quantity": 2},
            ]
        )


def test_order_create_rejects_too_many_items() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(
            items=[
                {"product_id": f"product-{index}", "quantity": 1}
                for index in range(7)
            ]
        )


def test_order_create_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(items=[{"product_id": "nova-headphones", "quantity": 1, "extra": True}])


def test_lab_run_validation() -> None:
    assert LabRunCreate().stock == 50
    assert LabRunCreate(stock=200, notification_delay_ms=2000).notification_delay_ms == 2000
    for stock in (0, 201):
        with pytest.raises(ValidationError):
            LabRunCreate(stock=stock)
    for delay in (-1, 2001):
        with pytest.raises(ValidationError):
            LabRunCreate(notification_delay_ms=delay)
    with pytest.raises(ValidationError):
        LabRunCreate(stock="50")
    with pytest.raises(ValidationError):
        LabRunCreate(stock=True)
