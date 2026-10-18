from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    order_status: str
    delivery_age: int | None
    proof_status: str | None
    expected_action: str
    expected_missing: list[str] = []


class AgentCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    prompt: str
    expected_tools: list[str]
    alternative_tool_sets: list[list[str]] = []
    required_patterns: list[str] = []
    forbidden_patterns: list[str] = []
    order_owned: bool = True
    existing_status: Literal["awaiting_review", "approved", "resolved", "rejected"] | None = None
    proof_status: str | None = "mismatched"


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    policy_cases: list[PolicyCase] = Field(min_length=1)
    agent_cases: list[AgentCase] = Field(min_length=1)
