from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.email_address import validate_address


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        return validate_address(value.strip().lower())


class RegisterRequest(LoginRequest):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    password: str = Field(min_length=12, max_length=128)


class VerifyRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")
