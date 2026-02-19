# Claude Coding Agent

A CLI coding assistant powered by Claude Opus 4.6. It runs in your terminal, accepts natural language instructions, and uses tools to read/write files, run commands, and search code.

## Setup

```bash
# Set your Anthropic API key
export ANTHROPIC_API_KEY='your-key-here'

# Install and create the `coding-agent` command
./install.sh
```

## Usage

```bash
# Interactive mode
coding-agent

# One-shot prompt
coding-agent "create a hello world script"

# Work in a specific directory
coding-agent -d ~/myproject

# Skip tool confirmation prompts
coding-agent --auto-approve

# Combine flags
coding-agent -d ~/myproject --auto-approve "fix the failing tests"
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/clear` | Reset conversation history |
| `/exit` | Exit the agent |
| `Ctrl+C` | Cancel current generation |

## Tools

The agent has access to these tools:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with optional offset/limit |
| `write_file` | Create or overwrite a file |
| `edit_file` | Replace a specific string in a file |
| `bash` | Execute a shell command (with confirmation) |
| `glob_search` | Find files matching a glob pattern |
| `grep_search` | Search file contents with regex |
| `list_directory` | List directory contents |

## Safety

- **Sandbox**: File operations are restricted to the working directory
- **Confirmation prompts**: Bash commands, file writes, and edits require confirmation (bypass with `--auto-approve`)
- **Safe commands**: Read-only commands like `ls`, `git status`, `cat` run without confirmation
- **Timeout**: Shell commands timeout after 120 seconds by default
- **Context management**: Long conversations are automatically summarized to stay within context limits

## Architecture

```
agent.py          CLI entry point, REPL loop, argument parsing
loop.py           Core agentic loop (call model → execute tools → repeat)
tools.py          Tool JSON schemas and executor functions
display.py        Rich-based streaming output and formatting
context.py        Conversation history and summarization
system_prompt.py  System prompt with runtime context injection
```

## Requirements

- Python 3.8+
- `anthropic` — Anthropic Python SDK
- `rich` — Terminal formatting
- `prompt_toolkit` — Interactive input with history
