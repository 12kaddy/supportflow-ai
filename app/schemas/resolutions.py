from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    amount_cents: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def validate_amount(self):
        if self.decision == "approve" and self.amount_cents is None:
            raise ValueError("Approval requires amount_cents")
        if self.decision == "reject" and self.amount_cents is not None:
            raise ValueError("Rejection cannot specify amount_cents")
        return self
