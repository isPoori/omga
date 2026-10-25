"""edit_file tool + context compression."""

from pathlib import Path

from agent.compress import compress_history, estimate_chars, needs_compression
from core.models import Message, ToolCall
from tools.edit import edit_file_tool


def test_edit_file_replace(tmp_path: Path):
    f = tmp_path / "a.py"
    f.write_text("def hello():\n    return 1\n", encoding="utf-8")
    tool = edit_file_tool(tmp_path)
    result = tool.run(
        path="a.py",
        old_string="return 1",
        new_string="return 2",
    )
    assert result["success"]
    assert "return 2" in f.read_text(encoding="utf-8")


def test_compress_history():
    msgs = [Message(role="system", content="You are OMGA")]
    for i in range(40):
        msgs.append(Message(role="user", content=("goal " + str(i) + " ") * 200))
        msgs.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id=f"c{i}", name="read_file", arguments={"path": f"f{i}.py"})],
            )
        )
        msgs.append(Message(role="tool", content=("x" * 500), name="read_file", tool_call_id=f"c{i}"))
    assert needs_compression(msgs, soft=5_000)
    out = compress_history(msgs, soft=5_000, keep_recent=8)
    assert estimate_chars(out) < estimate_chars(msgs)
    assert any("Compressed" in (m.content or "") for m in out if m.role == "system")
