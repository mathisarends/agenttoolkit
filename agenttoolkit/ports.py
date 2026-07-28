from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Literal, Protocol, overload, runtime_checkable

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Function(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: Function


class ChatMessage(BaseModel):
    role: Role
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    def to_openai_schema(self) -> dict[str, Any]: ...

    def parse_arguments(self, arguments: str) -> Any: ...


class ChatUsage(BaseModel):
    prompt_tokens: int
    prompt_cached_tokens: int | None = None
    prompt_cache_creation_tokens: int | None = None
    prompt_image_tokens: int | None = None
    completion_tokens: int
    total_tokens: int


class ChatCompletion[T](BaseModel):
    completion: T
    model: str
    thinking: str | None = None
    redacted_thinking: str | None = None
    usage: ChatUsage | None = None
    stop_reason: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class StreamEventType(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    END = "end"


class StreamTextDelta(BaseModel):
    type: Literal[StreamEventType.TEXT] = StreamEventType.TEXT
    delta: str


class StreamToolCall(BaseModel):
    type: Literal[StreamEventType.TOOL_CALL] = StreamEventType.TOOL_CALL
    tool_call: ToolCall


class StreamEnd(BaseModel):
    type: Literal[StreamEventType.END] = StreamEventType.END
    stop_reason: str | None = None
    usage: ChatUsage | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    completion: str = ""


type StreamEvent = StreamTextDelta | StreamToolCall | StreamEnd


class LLMPort(ABC):
    def __init__(
        self,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        stop: str | list[str] | None = None,
        seed: int | None = None,
        response_format: dict | None = None,
        timeout: float | None = 60.0,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.stop = stop
        self.seed = seed
        self.response_format = response_format
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_params = kwargs

    @overload
    async def call[T: BaseModel](
        self, messages: list[ChatMessage], output_format: type[T], **kwargs: Any
    ) -> ChatCompletion[T]: ...

    @overload
    async def call(
        self, messages: list[ChatMessage], output_format: None = None, **kwargs: Any
    ) -> ChatCompletion[str]: ...

    @abstractmethod
    async def call[T: BaseModel](
        self,
        messages: list[ChatMessage],
        output_format: type[T] | None = None,
        **kwargs: Any,
    ) -> ChatCompletion[T] | ChatCompletion[str]: ...

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[Tool] | None = None,
        tool_choice: Literal["auto", "required", "none"] = "auto",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...
