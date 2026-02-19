"""Display layer for terminal output using Rich."""

import sys

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()

# ── Streaming Text ────────────────────────────────────────────────────────────


class StreamingDisplay:
    """Accumulates streamed text and renders it as markdown when complete."""

    def __init__(self):
        self._buffer = ""
        self._live = Live(
            Text(""),
            console=console,
            refresh_per_second=15,
            vertical_overflow="visible",
        )

    def start(self):
        self._buffer = ""
        self._live.start()

    def update(self, text_delta: str):
        self._buffer += text_delta
        try:
            self._live.update(Markdown(self._buffer))
        except Exception:
            self._live.update(Text(self._buffer))

    def finish(self):
        # Render final markdown in the Live context so it replaces the
        # streaming preview cleanly, then stop.
        if self._buffer.strip():
            try:
                self._live.update(Markdown(self._buffer))
            except Exception:
                self._live.update(Text(self._buffer))
        self._live.stop()

    @property
    def text(self) -> str:
        return self._buffer


# ── Tool Call Display ─────────────────────────────────────────────────────────

# Descriptions for tool call headers
_TOOL_LABELS = {
    "read_file": "Reading file",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "bash": "Running command",
    "glob_search": "Searching for files",
    "grep_search": "Searching file contents",
    "list_directory": "Listing directory",
}


def show_tool_call(tool_name: str, tool_input: dict):
    """Display a tool call header."""
    label = _TOOL_LABELS.get(tool_name, tool_name)

    if tool_name in ("read_file", "write_file", "edit_file"):
        detail = tool_input.get("file_path", "")
    elif tool_name == "bash":
        detail = tool_input.get("command", "")
    elif tool_name == "glob_search":
        detail = tool_input.get("pattern", "")
    elif tool_name == "grep_search":
        detail = tool_input.get("pattern", "")
    elif tool_name == "list_directory":
        detail = tool_input.get("path", ".")
    else:
        detail = ""

    header = Text()
    header.append("  ", style="bold cyan")
    header.append(f"{label}", style="bold cyan")
    if detail:
        header.append(f": {detail}", style="cyan")
    console.print(header)


def show_tool_result(tool_name: str, result: str):
    """Display a tool result in a subdued style."""
    # Truncate very long results for display
    max_display = 3000
    truncated = result[:max_display]
    if len(result) > max_display:
        truncated += f"\n... ({len(result) - max_display} more characters)"

    console.print(
        Panel(
            Text(truncated, style="dim"),
            border_style="dim",
            expand=False,
            width=min(console.width, 120),
        )
    )


def show_error(message: str):
    """Display an error message."""
    console.print(f"[bold red]Error:[/bold red] {message}")


def show_info(message: str):
    """Display an informational message."""
    console.print(f"[dim]{message}[/dim]")


def show_welcome(working_dir: str):
    """Display the welcome banner."""
    console.print()
    console.print(
        Panel(
            "[bold]Coding Agent[/bold]\n"
            f"Working directory: [cyan]{working_dir}[/cyan]\n"
            "Type your request, or /help for commands.",
            border_style="blue",
            expand=False,
        )
    )
    console.print()


def show_help():
    """Display help text."""
    console.print(
        Markdown(
            """\
## Commands
- `/help` — Show this help message
- `/clear` — Clear conversation history
- `/exit` or `/quit` — Exit the agent
- `Ctrl+C` — Cancel current generation

## Tips
- Ask the agent to read, write, or edit files
- Ask it to run shell commands
- Ask it to search for code patterns
- Multi-line input: use `Alt+Enter` or `Meta+Enter` for a newline
"""
        )
    )


def show_confirm(message: str) -> bool:
    """Ask the user for confirmation. Returns True if confirmed."""
    try:
        response = console.input(f"[yellow]{message} (y/n): [/yellow]")
        return response.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
