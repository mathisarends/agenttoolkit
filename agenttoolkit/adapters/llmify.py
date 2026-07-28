from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel

from agenttoolkit.ports import (
    ChatCompletion,
    ChatMessage,
    ChatUsage,
    Function,
    LLMPort,
    Role,
    StreamEnd,
    StreamEvent,
    StreamTextDelta,
    StreamToolCall,
    Tool,
    ToolCall,
)

try:
    from llmify import (
        AssistantMessage,
        ChatModel,
        SystemMessage,
        ToolResultMessage,
        UserMessage,
    )
    from llmify import ToolCall as LlmifyToolCall
    from llmify.views import ChatInvokeUsage
    from llmify.views import StreamEnd as LlmifyStreamEnd
    from llmify.views import StreamTextDelta as LlmifyStreamTextDelta
    from llmify.views import StreamToolCall as LlmifyStreamToolCall
except ImportError as exc:
    raise ImportError(
        "LlmifyLLMPort requires the optional 'py-llmify' dependency. "
        "Install it with: pip install agenttoolkit[llmify]"
    ) from exc

_ROLE_TO_MESSAGE = {
    Role.SYSTEM: SystemMessage,
    Role.USER: UserMessage,
    Role.ASSISTANT: AssistantMessage,
}


def _to_llmify_tool_call(tool_call: ToolCall) -> LlmifyToolCall:
    return LlmifyToolCall(
        id=tool_call.id,
        function={
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    )


def _to_our_tool_call(tool_call: LlmifyToolCall) -> ToolCall:
    return ToolCall(
        id=tool_call.id,
        function=Function(
            name=tool_call.function.name, arguments=tool_call.function.arguments
        ),
    )


def _to_llmify_message(message: ChatMessage):
    if message.role == Role.TOOL:
        return ToolResultMessage(
            tool_call_id=message.tool_call_id or "", content=message.content or ""
        )

    if message.role == Role.ASSISTANT:
        return AssistantMessage(
            content=message.content,
            tool_calls=[_to_llmify_tool_call(call) for call in message.tool_calls],
        )

    return _ROLE_TO_MESSAGE[message.role](content=message.content or "")


def _to_our_usage(usage: ChatInvokeUsage | None) -> ChatUsage | None:
    if usage is None:
        return None

    return ChatUsage(
        prompt_tokens=usage.prompt_tokens,
        prompt_cached_tokens=usage.prompt_cached_tokens,
        prompt_cache_creation_tokens=usage.prompt_cache_creation_tokens,
        prompt_image_tokens=usage.prompt_image_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


class LlmifyLLMPort(LLMPort):
    def __init__(self, chat_model: ChatModel) -> None:
        super().__init__(model=chat_model.model)
        self._chat_model = chat_model

    async def call[T: BaseModel](
        self,
        messages: list[ChatMessage],
        output_format: type[T] | None = None,
        **kwargs: Any,
    ) -> ChatCompletion[T] | ChatCompletion[str]:
        llmify_messages = [_to_llmify_message(message) for message in messages]

        result = await self._chat_model.invoke(
            llmify_messages, output_format=output_format, **kwargs
        )

        return ChatCompletion(
            completion=result.completion,
            model=self._chat_model.model,
            thinking=result.thinking,
            redacted_thinking=result.redacted_thinking,
            usage=_to_our_usage(result.usage),
            stop_reason=result.stop_reason,
            tool_calls=[_to_our_tool_call(call) for call in result.tool_calls],
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[Tool] | None = None,
        tool_choice: Literal["auto", "required", "none"] = "auto",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        llmify_messages = [_to_llmify_message(message) for message in messages]

        async for event in self._chat_model.stream(
            llmify_messages, tools=tools, tool_choice=tool_choice, **kwargs
        ):
            if isinstance(event, LlmifyStreamTextDelta):
                yield StreamTextDelta(delta=event.delta)
            elif isinstance(event, LlmifyStreamToolCall):
                yield StreamToolCall(tool_call=_to_our_tool_call(event.tool_call))
            elif isinstance(event, LlmifyStreamEnd):
                yield StreamEnd(
                    stop_reason=event.stop_reason,
                    usage=_to_our_usage(event.usage),
                    tool_calls=[_to_our_tool_call(call) for call in event.tool_calls],
                    completion=event.completion,
                )
