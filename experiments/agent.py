import json
from collections.abc import Callable
from typing import Any

from llmify import (
    AssistantMessage,
    ChatModel,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from pydantic import BaseModel

from agenttoolkit.tools import ActionResult, Tools, ToolSchemaFormat


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


OnToolCall = Callable[[str, dict[str, Any]], None]
OnToolResult = Callable[[str, ActionResult[object]], None]


class Agent:
    def __init__(
        self,
        model: ChatModel,
        tools: Tools,
        *,
        system_prompt: str | None = None,
        on_tool_call: OnToolCall | None = None,
        on_tool_result: OnToolResult | None = None,
        confirm: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._messages: list[Message] = []
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._confirm = confirm
        if system_prompt:
            self._messages.append(SystemMessage(content=system_prompt))

    async def run(self, user_input: str) -> str:
        self._messages.append(UserMessage(content=user_input))

        while True:
            schema = self._tools.get_schema(ToolSchemaFormat.OPENAI)
            completion = await self._model.invoke(self._messages, tools=schema)

            self._messages.append(
                AssistantMessage(
                    content=completion.completion or None,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                return completion.completion

            for call in completion.tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                if self._on_tool_call:
                    self._on_tool_call(call.function.name, arguments)

                tool = self._tools.get(call.function.name)
                if (
                    tool is not None
                    and tool.requires_approval
                    and self._confirm is not None
                    and not self._confirm(call.function.name, arguments)
                ):
                    result = ActionResult[object].fail("Declined by user")
                else:
                    result = await self._tools.execute(call.function.name, arguments)

                if self._on_tool_result:
                    self._on_tool_result(call.function.name, result)

                payload = (
                    {"ok": True, "result": result.result}
                    if result.ok
                    else {"ok": False, "error": result.error}
                )
                self._messages.append(
                    ToolResultMessage(
                        tool_call_id=call.id,
                        content=json.dumps(payload, default=_json_default),
                    )
                )
