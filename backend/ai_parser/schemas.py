from pydantic import BaseModel, ConfigDict, Field, confloat, conint


class OrderItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    qty: conint(ge=1) = 1
    size: str | None = None
    color: str | None = None


class CustomerInfo(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class DeliveryInfo(BaseModel):
    address: str | None = None
    city: str | None = None


class OrderExtract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chain_of_thought: str = ""
    items: list[OrderItem] = Field(default_factory=list)
    customer: CustomerInfo = Field(default_factory=CustomerInfo)
    delivery: DeliveryInfo = Field(default_factory=DeliveryInfo)
    comment: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    confidence: confloat(ge=0.0, le=1.0) = 0.0

