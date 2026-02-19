"""Core agentic loop: call model → execute tools → repeat."""

import json

import anthropic

from context import estimate_tokens, needs_summarization, summarize_conversation
from display import (
    StreamingDisplay,
    show_confirm,
    show_error,
    show_info,
    show_tool_call,
    show_tool_result,
)
from tools import TOOL_SCHEMAS, execute_tool

MAX_ITERATIONS = 50

# Commands considered safe enough to run without confirmation
SAFE_COMMAND_PREFIXES = (
    "ls",
    "pwd",
    "echo",
    "cat ",
    "head ",
    "tail ",
    "wc ",
    "find ",
    "which ",
    "whoami",
    "date",
    "uname",
    "python --version",
    "python3 --version",
    "node --version",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "git remote",
    "pip list",
    "pip show",
    "npm list",
    "cargo --version",
    "rustc --version",
    "go version",
)


def _is_safe_command(command: str) -> bool:
    """Check if a bash command is safe to run without confirmation."""
    cmd = command.strip()
    return any(cmd == prefix or cmd.startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES)


def _confirm_tool(tool_name: str, tool_input: dict) -> bool:
    """Ask user for confirmation before executing a tool. Returns True if approved."""
    if tool_name == "bash":
        command = tool_input.get("command", "")
        if _is_safe_command(command):
            return True
        return show_confirm(f"Run command: {command}?")

    if tool_name == "write_file":
        path = tool_input.get("file_path", "")
        return show_confirm(f"Write file: {path}?")

    if tool_name == "edit_file":
        path = tool_input.get("file_path", "")
        return show_confirm(f"Edit file: {path}?")

    # read, glob, grep, list_directory are always safe
    return True


def agent_loop(
    client: anthropic.Anthropic,
    messages: list[dict],
    system_prompt: str,
    working_dir: str,
    auto_approve: bool = False,
) -> list[dict]:
    """Run the agentic loop until the model stops or hits the iteration limit.

    Args:
        client: Anthropic client.
        messages: Conversation messages (modified in-place).
        system_prompt: System prompt string.
        working_dir: Working directory for tool execution.
        auto_approve: If True, skip confirmation prompts for all tools.

    Returns:
        The updated messages list.
    """
    for iteration in range(MAX_ITERATIONS):
        # Summarize if needed
        if needs_summarization(messages):
            show_info("Summarizing earlier conversation to save context...")
            messages[:] = summarize_conversation(client, messages)

        # Call the model with streaming
        try:
            stream = client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=8192,
                system=system_prompt,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except anthropic.APIError as e:
            show_error(f"API error: {e}")
            break

        # Process the streaming response
        text_content = ""
        tool_calls = []
        display = StreamingDisplay()

        try:
            with stream as s:
                display.start()
                for event in s:
                    if hasattr(event, "type"):
                        if event.type == "content_block_start":
                            if hasattr(event.content_block, "type"):
                                if event.content_block.type == "text":
                                    pass  # Text streaming handled by deltas
                                elif event.content_block.type == "tool_use":
                                    # Finish text display before tool call
                                    if display.text.strip():
                                        display.finish()
                                        display = StreamingDisplay()
                                    tool_calls.append({
                                        "id": event.content_block.id,
                                        "name": event.content_block.name,
                                        "input_json": "",
                                    })
                        elif event.type == "content_block_delta":
                            if hasattr(event.delta, "type"):
                                if event.delta.type == "text_delta":
                                    display.update(event.delta.text)
                                    text_content += event.delta.text
                                elif event.delta.type == "input_json_delta":
                                    if tool_calls:
                                        tool_calls[-1]["input_json"] += event.delta.partial_json
                display.finish()

                # Get the final message for stop reason
                response = s.get_final_message()
                stop_reason = response.stop_reason

        except KeyboardInterrupt:
            display.finish()
            show_info("Generation cancelled.")
            # Append what we have so far
            if text_content.strip():
                messages.append({"role": "assistant", "content": text_content})
            break
        except anthropic.APIError as e:
            display.finish()
            show_error(f"API error during streaming: {e}")
            break

        # Build the assistant message content blocks
        assistant_content = []
        if text_content:
            assistant_content.append({"type": "text", "text": text_content})

        # Parse and add tool use blocks
        parsed_tools = []
        for tc in tool_calls:
            try:
                tool_input = json.loads(tc["input_json"]) if tc["input_json"] else {}
            except json.JSONDecodeError:
                tool_input = {}
            parsed_tools.append({
                "id": tc["id"],
                "name": tc["name"],
                "input": tool_input,
            })
            assistant_content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tool_input,
            })

        if not assistant_content:
            assistant_content = [{"type": "text", "text": ""}]

        messages.append({"role": "assistant", "content": assistant_content})

        # If no tool calls, we're done
        if not parsed_tools:
            break

        # Execute tools and collect results
        tool_results = []
        for tool in parsed_tools:
            show_tool_call(tool["name"], tool["input"])

            # Confirmation check
            if not auto_approve and not _confirm_tool(tool["name"], tool["input"]):
                result_text = "Tool execution cancelled by user."
                show_info(result_text)
            else:
                result_text = execute_tool(tool["name"], tool["input"], working_dir)
                show_tool_result(tool["name"], result_text)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool["id"],
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})

        # If model indicated end_turn despite having tool calls, break
        if stop_reason == "end_turn" and not parsed_tools:
            break
    else:
        show_error(f"Reached maximum iteration limit ({MAX_ITERATIONS}).")

    return messages
