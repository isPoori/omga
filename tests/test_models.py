"""Message / tool-call protocol tests."""

from core.models import Message, ToolCall


def test_assistant_tool_calls_serialize():
    msg = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
    )
    data = msg.to_openai()
    assert data["role"] == "assistant"
    assert data["content"] is None
    assert data["tool_calls"][0]["id"] == "c1"
    assert data["tool_calls"][0]["function"]["name"] == "read_file"
    assert '"path"' in data["tool_calls"][0]["function"]["arguments"]


def test_tool_result_serialize():
    msg = Message(role="tool", content='{"ok": true}', name="read_file", tool_call_id="c1")
    data = msg.to_openai()
    assert data["tool_call_id"] == "c1"
    assert data["name"] == "read_file"
