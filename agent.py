#!/usr/bin/env python3
"""CLI entry point for the coding agent."""

import argparse
import os
import sys

import anthropic
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from display import console, show_error, show_help, show_info, show_welcome
from loop import agent_loop
from system_prompt import build_system_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A CLI coding agent powered by Claude."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Initial prompt to send (runs non-interactively if provided with --no-interactive).",
    )
    parser.add_argument(
        "-d",
        "--directory",
        default=os.getcwd(),
        help="Working directory (default: current directory).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip confirmation prompts for all tool executions.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Run in non-interactive mode (exit after processing the initial prompt).",
    )
    return parser.parse_args()


def create_prompt_session() -> PromptSession:
    """Create a prompt_toolkit session with history and key bindings."""
    history_file = os.path.expanduser("~/.coding_agent_history")
    history = FileHistory(history_file)

    # Key bindings: Alt+Enter for newline, Enter for submit
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        history=history,
        key_bindings=bindings,
        multiline=False,
    )


def handle_slash_command(command: str, messages: list[dict]) -> bool:
    """Handle slash commands. Returns True if the command was handled."""
    cmd = command.strip().lower()

    if cmd in ("/exit", "/quit"):
        show_info("Goodbye!")
        sys.exit(0)

    if cmd == "/clear":
        messages.clear()
        show_info("Conversation cleared.")
        return True

    if cmd == "/help":
        show_help()
        return True

    return False


def main():
    args = parse_args()
    working_dir = os.path.abspath(args.directory)

    if not os.path.isdir(working_dir):
        show_error(f"Directory not found: {working_dir}")
        sys.exit(1)

    # Initialize Anthropic client
    # The SDK auto-detects ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, and
    # ANTHROPIC_CUSTOM_HEADERS from the environment, so we only need to
    # check that at least one auth mechanism is configured.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if not api_key and not base_url:
        show_error(
            "ANTHROPIC_API_KEY environment variable is not set.\n"
            "Set it with: export ANTHROPIC_API_KEY='your-key-here'"
        )
        sys.exit(1)

    # Let the SDK pick up all env vars automatically.
    # When using a proxy (ANTHROPIC_BASE_URL), a dummy key satisfies the SDK.
    if not api_key and base_url:
        client = anthropic.Anthropic(api_key="dummy")
    else:
        client = anthropic.Anthropic()
    system_prompt = build_system_prompt(working_dir)
    messages: list[dict] = []

    show_welcome(working_dir)

    # If an initial prompt was provided, run it first
    if args.prompt:
        console.print(f"[bold green]You:[/bold green] {args.prompt}")
        console.print()
        messages.append({"role": "user", "content": args.prompt})
        try:
            messages = agent_loop(
                client, messages, system_prompt, working_dir, args.auto_approve
            )
        except KeyboardInterrupt:
            console.print()
            show_info("Cancelled.")

        if args.no_interactive:
            return

    # Interactive REPL
    session = create_prompt_session()

    while True:
        try:
            user_input = session.prompt("You: ").strip()
        except KeyboardInterrupt:
            console.print()
            continue
        except EOFError:
            show_info("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            if handle_slash_command(user_input, messages):
                continue

        console.print()
        messages.append({"role": "user", "content": user_input})

        try:
            messages = agent_loop(
                client, messages, system_prompt, working_dir, args.auto_approve
            )
        except KeyboardInterrupt:
            console.print()
            show_info("Cancelled.")

        console.print()


if __name__ == "__main__":
    main()
