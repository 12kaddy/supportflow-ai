import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def test_valid_chat():
    assert ChatRequest(message="Hello", thread_id="test-1").message == "Hello"


def test_empty_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(message="", thread_id="test-1")
