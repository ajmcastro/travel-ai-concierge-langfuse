"""Tests for AnthropicProvider's message/tool translation (Milestone 5).

Pure data transformation — no network, no credentials — verifying the
output shape matches the installed SDK's actual types (ToolUseBlockParam,
ToolResultBlockParam, ToolParam), confirmed by introspection before this
code was written (see docs/EXPERIMENTS.md).
"""

from travel_ai_concierge.providers.llm.anthropic_provider import (
    _to_anthropic_messages,
    _to_anthropic_tools,
)
from travel_ai_concierge.providers.llm.base import Message, ToolCall, ToolSpec


def test_system_message_is_excluded():
    messages = [Message(role="system", content="be nice"), Message(role="user", content="hi")]
    result = _to_anthropic_messages(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"


def test_plain_user_message():
    result = _to_anthropic_messages([Message(role="user", content="hello")])
    assert result == [{"role": "user", "content": "hello"}]


def test_assistant_tool_call_becomes_tool_use_block():
    call = ToolCall(id="abc123", name="search_hotels", arguments={"destination_id": "porto"})
    messages = [Message(role="assistant", content="", tool_calls=[call])]

    result = _to_anthropic_messages(messages)

    assert result == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "abc123",
                    "name": "search_hotels",
                    "input": {"destination_id": "porto"},
                }
            ],
        }
    ]


def test_assistant_message_with_text_and_tool_call():
    call = ToolCall(id="abc123", name="search_hotels", arguments={})
    messages = [Message(role="assistant", content="Let me check.", tool_calls=[call])]

    result = _to_anthropic_messages(messages)

    content = result[0]["content"]
    assert content[0] == {"type": "text", "text": "Let me check."}
    assert content[1]["type"] == "tool_use"


def test_tool_result_becomes_a_user_message_with_tool_result_block():
    messages = [
        Message(role="tool", content='{"found": true}', tool_call_id="abc123", name="search")
    ]

    result = _to_anthropic_messages(messages)

    assert result == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "abc123", "content": '{"found": true}'}
            ],
        }
    ]


def test_tools_translate_to_anthropic_tool_param_shape():
    specs = [
        ToolSpec(
            name="search_hotels",
            description="Search hotels.",
            input_schema={"type": "object", "properties": {}},
        )
    ]

    result = _to_anthropic_tools(specs)

    assert result == [
        {
            "name": "search_hotels",
            "description": "Search hotels.",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
