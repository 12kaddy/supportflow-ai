from pydantic import BaseModel, Field


class DisputeRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=40)
    issue: str = Field(min_length=1, max_length=4000, pattern=r"\S")
