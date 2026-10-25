"""
Tool registry — builds the full set of tools for the agent.

Tools self-assemble from factories bound to a project root, optional
memory store, skills catalog, and a subagent factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from tools.base import Tool
from tools.edit import edit_file_tool
from tools.files import (
    delete_file_tool,
    list_files_tool,
    read_file_tool,
    search_tool,
    write_file_tool,
)
from tools.git import git_tools
from tools.process import process_tools
from tools.shell import shell_tool


class ToolRegistry:
    def __init__(
        self,
        root: str | Path,
        *,
        store: Any | None = None,
        skills: Any | None = None,
        make_child: Callable[[str], str] | None = None,
        enable_delegate: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.store = store
        self.skills = skills
        self.make_child = make_child
        self.enable_delegate = enable_delegate
        self.tools: list[Tool] = []
        self.by_name: dict[str, Tool] = {}
        self._register()

    def _register(self) -> None:
        factories = [
            read_file_tool,
            edit_file_tool,
            write_file_tool,
            delete_file_tool,
            list_files_tool,
            search_tool,
            shell_tool,
        ]
        for factory in factories:
            self.add(factory(self.root))
        for tool in git_tools(self.root):
            self.add(tool)
        for tool in process_tools():
            self.add(tool)

        if self.store is not None:
            from tools.memory_tools import memory_tools

            for tool in memory_tools(self.store, cwd=str(self.root)):
                self.add(tool)

        if self.skills is not None:
            from tools.skills_tools import skills_tools

            for tool in skills_tools(self.skills, self.root):
                self.add(tool)

        if self.enable_delegate and self.make_child is not None:
            from tools.delegate import delegate_tool

            self.add(delegate_tool(make_child=self.make_child))

    def add(self, tool: Tool) -> None:
        self.tools.append(tool)
        self.by_name[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.by_name.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai() for t in self.tools]

    def names(self) -> list[str]:
        return [t.name for t in self.tools]
