from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class OrderItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    quantity: StrictInt = Field(ge=1, le=5)  # <-- Cambiado int por StrictInt

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_json_number_type(cls, value: object) -> object:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("quantity must be an integer")
        return value

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrderItemIn] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_unique_products(self) -> "OrderCreate":
        identifiers = [item.product_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("items must reference distinct products")
        return self


class LabRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock: StrictInt = Field(default=50, ge=1, le=200)
    notification_delay_ms: StrictInt = Field(default=0, ge=0, le=2000)
