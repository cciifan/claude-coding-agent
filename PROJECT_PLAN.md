# PROJECT PLAN: CLI Coding Agent

A comprehensive design document for a terminal-based coding agent powered by Claude Opus 4.6. This document describes every module, design decision, and implementation detail in enough depth to rebuild the project from scratch.

---

## 1. Project Overview

### What It Is

A command-line coding agent that accepts natural language instructions, reasons about code, and takes action — reading files, writing code, running shell commands, and searching codebases — all inside a terminal REPL.

### Core Concept: The Agentic Loop

The architecture follows the **agentic loop** pattern:

```
User prompt
    ↓
Call Claude API (streaming)
    ↓
Model returns text + tool calls
    ↓
Execute tools → collect results
    ↓
Feed results back to model
    ↓
Repeat until model stops (or 50 iterations)
```

The model decides what to do next. The code just orchestrates: send messages, parse responses, execute tools, append results, repeat. There is no hard-coded task logic — Claude drives every decision.

### Dependencies

Only three external packages (defined in `requirements.txt`):

| Package | Min Version | Purpose |
|---------|-------------|---------|
| `anthropic` | ≥0.40.0 | Claude API client with streaming support |
| `rich` | ≥13.0.0 | Terminal UI: Markdown rendering, panels, live streaming |
| `prompt_toolkit` | ≥3.0.0 | REPL input with history, key bindings, multiline support |

Everything else uses the Python standard library.

---

## 2. Architecture

### Module Relationship Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      agent.py (entry point)                  │
│  CLI argument parsing, REPL, slash commands                  │
│  Initializes Anthropic client, manages session               │
└──────────────┬───────────────────────────────────────────────┘
               │ calls agent_loop() each turn
               ▼
┌──────────────────────────────────────────────────────────────┐
│                      loop.py (agentic loop)                  │
│  Streaming API calls, event parsing, tool dispatch           │
│  Confirmation flow, iteration safety (max 50)                │
│                                                              │
│  ┌──────────┐   ┌───────────┐   ┌──────────┐               │
│  │ tools.py │   │display.py │   │context.py│               │
│  │ 7 tools  │   │ Rich UI   │   │ token    │               │
│  │ sandbox  │   │ streaming │   │ summary  │               │
│  └──────────┘   └───────────┘   └──────────┘               │
└──────────────────────────────────────────────────────────────┘
               ▲
               │ system prompt injected per call
┌──────────────┴───────────────────────────────────────────────┐
│                   system_prompt.py                            │
│  Dynamic prompt with runtime context (OS, date, shell)       │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User input
  → agent.py adds to messages list (role: "user")
  → agent.py calls agent_loop(client, messages, system_prompt, working_dir)
    → context.py checks token count; summarizes if > 150K tokens
    → loop.py calls Claude API (claude-opus-4-6, streaming, max_tokens=8192)
    → loop.py parses stream events:
        - text deltas → display.py renders live Markdown
        - tool_use blocks → parsed into (name, input) pairs
    → For each tool call:
        - display.py shows tool invocation
        - loop.py checks confirmation (safe-command whitelist / user prompt)
        - tools.py executes the tool within sandbox
        - display.py shows result
    → Tool results appended as role: "user" message with tool_result blocks
    → Loop repeats (up to 50 iterations)
  → agent.py receives updated messages list
  → REPL prompts for next input
```

### Module Responsibility Map

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `tools.py` | 464 | Tool schemas (7), executor functions, sandbox enforcement, dispatcher |
| `display.py` | 166 | Rich-based terminal UI, streaming display, tool rendering, confirmations |
| `system_prompt.py` | 41 | Dynamic system prompt with runtime context injection |
| `context.py` | 122 | Token estimation, summarization trigger, conversation compression |
| `loop.py` | 227 | Core agentic loop, streaming, event parsing, tool execution flow |
| `agent.py` | 171 | CLI entry point, REPL, argument parsing, slash commands |
| **Total** | **~1,191** | |

Plus `install.sh` (65 lines) for installation.

---

## 3. Step-by-Step Build Guide

Each step creates one module. Steps are ordered so each builds on the previous ones, teaching someone to reconstruct the entire system incrementally.

---

### Step 1: Tool Definitions (`tools.py`)

**Why it exists:** Claude needs tools to interact with the filesystem and shell. This module defines what tools are available (as JSON schemas the API understands) and implements the code that runs when each tool is called.

**What it does:**

1. **Defines 7 tool schemas** (`TOOL_SCHEMAS`, lines 13–175) — a list of dictionaries in the Claude API's tool format. Each schema has a `name`, `description`, and `input_schema` with JSON Schema properties.

2. **Implements 7 executor functions** — one per tool, each taking `(params: dict, working_dir: str) -> str`.

3. **Enforces a file sandbox** — all file operations are confined to the working directory.

4. **Provides a dispatcher** — `execute_tool()` routes a tool name to its executor.

#### The 7 Tools

| Tool | Executor | Purpose |
|------|----------|---------|
| `read_file` | `execute_read_file` (line 198) | Read a file with optional offset/limit, returns numbered lines |
| `write_file` | `execute_write_file` (line 232) | Create or overwrite a file, auto-creates parent directories |
| `edit_file` | `execute_edit_file` (line 248) | Exact string replacement in a file |
| `bash` | `execute_bash` (line 290) | Run a shell command via `subprocess.run`, 120s default timeout |
| `glob_search` | `execute_glob_search` (line 318) | Search for files by glob pattern, max 200 results |
| `grep_search` | `execute_grep_search` (line 350) | Recursive regex content search, max 200 results, skips `.git`/`node_modules`/`__pycache__` |
| `list_directory` | `execute_list_directory` (line 401) | List directory entries with type and human-readable sizes |

#### Sandbox Enforcement

Two helper functions enforce the sandbox:

```python
def _resolve_path(path: str, working_dir: str) -> str:
    """If path is relative, join with working_dir. Then resolve symlinks via os.path.realpath()."""

def _check_within_sandbox(resolved: str, working_dir: str) -> str | None:
    """Returns error message if resolved path doesn't start with working_dir, else None."""
```

Every file-touching executor calls `_resolve_path()` then `_check_within_sandbox()` before proceeding. This means:
- Relative paths are resolved against the working directory.
- Absolute paths are allowed only if they fall within the working directory.
- Symlinks are resolved first (`os.path.realpath()`), so a symlink pointing outside the sandbox is blocked.

#### The Dispatcher Pattern

```python
EXECUTORS = {
    "read_file": execute_read_file,
    "write_file": execute_write_file,
    "edit_file": execute_edit_file,
    "bash": execute_bash,
    "glob_search": execute_glob_search,
    "grep_search": execute_grep_search,
    "list_directory": execute_list_directory,
}

def execute_tool(tool_name: str, tool_input: dict, working_dir: str) -> str:
    executor = EXECUTORS.get(tool_name)
    if not executor:
        return f"Unknown tool: {tool_name}"
    return executor(tool_input, working_dir)
```

The loop calls `execute_tool(name, input, dir)` without knowing which specific executor runs. Adding a new tool means: add a schema to `TOOL_SCHEMAS`, write an executor function, add it to `EXECUTORS`.

#### Key Implementation Details

- **`edit_file`** uses exact string matching (`old_string` must appear in the file). If it appears more than once and `replace_all` is not `True`, the edit is rejected as ambiguous. This is intentional — see §4 for why.
- **`bash`** uses `subprocess.run()` with `shell=True`, `capture_output=True`, `text=True`, and a configurable `timeout` (default 120 seconds). On timeout, it returns an error message rather than crashing.
- **`grep_search`** walks the directory tree manually with `os.walk()`, applies an `include` glob filter, compiles the regex pattern, and searches line by line. It skips `.git`, `node_modules`, and `__pycache__` directories.

---

### Step 2: Display Layer (`display.py`)

**Why it exists:** The agent streams text from Claude token-by-token. A display layer turns that stream into a smooth terminal experience — live-updating Markdown, styled tool call headers, truncated results, and confirmation prompts.

**What it does:**

1. **`StreamingDisplay` class** (line 17) — Accumulates text deltas and renders them as live Markdown.
2. **Tool rendering functions** — `show_tool_call()` and `show_tool_result()` for styled tool output.
3. **Utility functions** — `show_error()`, `show_info()`, `show_welcome()`, `show_help()`, `show_confirm()`.

#### The `StreamingDisplay` Class

```python
class StreamingDisplay:
    def __init__(self):
        self._buffer = ""
        self._live = Live(
            Text(""),
            console=console,
            refresh_per_second=15,  # 15 fps cap
            transient=True,
        )
```

**How it works:**

1. `start()` — Clears the buffer, starts the Rich `Live` context. The display area is "transient" — it gets replaced by the final render when streaming ends.
2. `update(text_delta)` — Appends the delta to `_buffer`, renders the full buffer as `Markdown`. Falls back to plain `Text` if Markdown rendering fails.
3. `finish()` — Does a final Markdown render, stops the `Live` context. The final content is printed permanently.
4. `text` property — Returns the raw accumulated text.

**Why 15fps:** The `refresh_per_second=15` rate limits terminal redraws. Token deltas arrive much faster (possibly hundreds per second). Without throttling, the terminal would flicker and consume excessive CPU. 15fps is smooth enough to feel real-time.

#### Tool Call and Result Rendering

`show_tool_call()` (line 69) prints a styled header showing what tool is being used. It maps tool names to human-readable labels:

```python
_TOOL_LABELS = {
    "read_file": "Reading file",
    "write_file": "Writing file",
    "edit_file": "Editing file",
    "bash": "Running command",
    "glob_search": "Searching for files",
    "grep_search": "Searching file contents",
    "list_directory": "Listing directory",
}
```

`show_tool_result()` (line 94) displays the result in a dim `Panel`, truncated to **3,000 characters** (line 97) to keep the terminal manageable. Panel width is capped at `min(console.width, 120)`.

#### Confirmation Prompt

`show_confirm(message: str) -> bool` (line 158) — Prints a yellow prompt and reads `y/n` input. Returns `True` only if the user types `y` or `yes` (case-insensitive). Any other input (including just pressing Enter) returns `False`.

---

### Step 3: System Prompt (`system_prompt.py`)

**Why it exists:** Claude needs a system prompt that tells it how to behave as a coding agent. This prompt also needs runtime context — what OS is this, what directory are we in, what's today's date — so the model can give accurate platform-specific advice.

**What it does:**

A single function `build_system_prompt(working_dir: str) -> str` (line 8) returns an f-string that includes:

1. **Runtime context block:**
   - Working directory (`working_dir` parameter)
   - Platform and release (`platform.system()` + `platform.release()`)
   - Current date (`datetime.now().strftime("%Y-%m-%d")`)
   - Shell (`os.environ.get("SHELL", "unknown")`)

2. **Behavioral guidelines:**
   1. Read before edit — always read a file before modifying it
   2. Minimal changes — only change what's necessary
   3. Security — avoid destructive commands
   4. Explain your work — describe what you're doing and why
   5. Use the right tool — pick the most appropriate tool for each task
   6. Error handling — handle errors gracefully
   7. File paths relative to working directory
   8. Bash safety — be careful with shell commands

**Why guidelines are in the prompt:** The system prompt is the only reliable channel for behavioral instructions. The model doesn't have a separate "config" — everything it knows about how to behave comes from the system prompt. Embedding guidelines here ensures they're always present in context, regardless of conversation length or summarization.

---

### Step 4: Context Management (`context.py`)

**Why it exists:** Claude has a finite context window. Long coding sessions accumulate thousands of messages with file contents, command outputs, and tool results. Without management, the context would exceed limits and the API call would fail. This module estimates context size and automatically summarizes when needed.

**What it does:**

1. **`estimate_tokens(messages)`** (line 13) — Estimates the token count by dividing total character count by 4 (the `CHARS_PER_TOKEN` constant). It walks through all messages, handling text blocks, `tool_use` blocks (serializes input as JSON), and `tool_result` blocks (which can have nested content).

2. **`needs_summarization(messages)`** (line 40) — Returns `True` if `estimate_tokens(messages) > 150_000`.

3. **`summarize_conversation(client, messages)`** (line 45) — The core function. Here's how it works:

#### The Summarization Strategy

```
All messages: [m1, m2, m3, ..., m_n-20, m_n-19, ..., m_n]
                    ↑ older messages ↑     ↑ recent 20 ↑

Step 1: Split into older_messages and recent_messages (last 20 kept verbatim)
Step 2: Compress older_messages into a text summary
Step 3: Return [summary_as_user_msg, summary_as_assistant_msg, ...recent_messages]
```

**Two-tier model strategy:** Summarization uses `claude-sonnet-4-20250514` (not Opus) with `max_tokens=1024`. Sonnet is cheaper and faster — summarization doesn't need Opus-level reasoning, it just needs to capture key facts.

**Truncation before summarization:** Each older message is truncated to 2,000 characters, and tool results are truncated to 500 characters. This prevents the summarization call itself from being too large.

**Summary-as-synthetic-messages:** The summary is injected as two messages:
- A `user` message: `"Here is a summary of our conversation so far: {summary}"`
- An `assistant` message: `"Understood. I have the context from our previous conversation..."`

This approach works because the Claude API expects alternating user/assistant messages. The synthetic pair maintains the correct message structure while giving the model the context it needs.

**Fallback:** If the API call fails, it falls back to a hardcoded truncation notice:
```
"Previous conversation was too long and has been truncated. Recent context is preserved."
```

#### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `CHARS_PER_TOKEN` | 4 | Character-to-token estimation ratio |
| `MAX_CONTEXT_TOKENS` | 150,000 | Summarization trigger threshold |
| `RECENT_MESSAGES_TO_KEEP` | 20 | Messages kept verbatim (not summarized) |

---

### Step 5: Agentic Loop (`loop.py`)

**Why it exists:** This is the engine. It ties together the API, tools, display, and context management into the core loop that makes the agent work. Without this module, you'd have tools and a UI but no way to connect them to the model.

**What it does:**

The `agent_loop()` function (line 78) runs the full cycle:

```python
def agent_loop(
    client: anthropic.Anthropic,
    messages: list[dict],
    system_prompt: str,
    working_dir: str,
    auto_approve: bool = False
) -> list[dict]:
```

#### The Loop, Step by Step

```
for iteration in range(MAX_ITERATIONS):  # max 50
    1. Check context size → summarize if needed (context.py)
    2. Call Claude API with streaming:
       - model: "claude-opus-4-6"
       - max_tokens: 8192
       - system: system_prompt
       - tools: TOOL_SCHEMAS
       - messages: conversation history
    3. Process stream events:
       - content_block_start (type "text") → start StreamingDisplay
       - content_block_start (type "tool_use") → start capturing tool call
       - content_block_delta (text_delta) → update streaming display
       - content_block_delta (input_json_delta) → accumulate tool input JSON
       - message_stop → done
    4. Build assistant message from accumulated text + tool blocks
    5. Append assistant message to conversation
    6. If no tool calls → break (model is done)
    7. For each tool call:
       a. Show the tool invocation (display.py)
       b. Check confirmation:
          - auto_approve=True → skip
          - Read-only tools (read_file, glob, grep, list_dir) → auto-approve
          - Safe bash commands → auto-approve
          - Everything else → prompt user
       c. If denied → append "Tool execution cancelled by user"
       d. If approved → execute_tool() (tools.py), show result
    8. Append all tool results as a single "user" message
    9. Continue loop
else:
    # Reached 50 iterations without stopping
    show_error("Maximum iterations reached")
```

#### Manual Stream Event Parsing

The loop doesn't use SDK convenience methods for stream processing. Instead, it manually processes raw events from `client.messages.stream()`:

```python
with client.messages.stream(...) as stream:
    for event in stream:
        if event.type == "content_block_start":
            if event.content_block.type == "text":
                streaming_display.start()
            elif event.content_block.type == "tool_use":
                current_tool_name = event.content_block.name
                current_tool_id = event.content_block.id
                current_tool_input_json = ""
        elif event.type == "content_block_delta":
            if event.delta.type == "text_delta":
                streaming_display.update(event.delta.text)
            elif event.delta.type == "input_json_delta":
                current_tool_input_json += event.delta.partial_json
```

This gives fine-grained control over rendering (text is displayed as it arrives) and tool input parsing (JSON fragments are accumulated and parsed only when complete). See §4 for why this approach was chosen over SDK helpers.

#### Confirmation Flow

The `_confirm_tool()` function (line 58) implements a tiered approval system:

| Tool | Requires Confirmation? |
|------|----------------------|
| `read_file`, `glob_search`, `grep_search`, `list_directory` | Never — read-only operations |
| `bash` with safe command prefix | Never — the 28-entry safe-command whitelist |
| `bash` with other commands | Yes |
| `write_file`, `edit_file` | Yes — file modifications always need approval |

The safe-command whitelist (`SAFE_COMMAND_PREFIXES`, lines 21–49) contains 28 command prefixes:

```
ls, pwd, echo, cat, head, tail, wc, find, which, whoami,
date, uname, python --version, python3 --version, node --version,
git status, git log, git diff, git branch, git show, git remote,
pip list, pip show, npm list, cargo --version, rustc --version, go version
```

The check is prefix-based: `command.strip().startswith(prefix)`.

#### KeyboardInterrupt Handling

If the user presses Ctrl+C during streaming (line 154), the generation is cancelled gracefully:
- Partial text is kept and appended to the messages list
- The loop breaks (not crashes)
- The REPL returns to the prompt

#### Iteration Safety Limit

`MAX_ITERATIONS = 50` (line 18). If the model keeps calling tools for 50 iterations without stopping, the loop breaks and shows an error. This prevents runaway tool-calling loops that could consume API credits or run destructive commands indefinitely.

---

### Step 6: CLI Entry Point (`agent.py`)

**Why it exists:** Someone needs to start the program, parse arguments, set up the API client, and run the interactive loop. This is the glue that ties everything together into a usable CLI tool.

**What it does:**

#### Argument Parsing (`parse_args`, line 18)

| Argument | Flags | Default | Description |
|----------|-------|---------|-------------|
| `prompt` | positional, optional | `None` | Initial prompt for one-shot mode |
| `--directory` / `-d` | `-d` | `os.getcwd()` | Working directory |
| `--auto-approve` | flag | `False` | Skip all confirmation prompts |
| `--no-interactive` | flag | `False` | Exit after processing initial prompt |

#### REPL Setup (`create_prompt_session`, line 47)

Uses `prompt_toolkit.PromptSession` with:
- **FileHistory** — persists input history to `~/.coding_agent_history` (line 49)
- **Key binding** — `Escape + Enter` inserts a newline (for multi-line input), regular `Enter` submits (line 55–57)
- **`multiline=False`** — regular Enter submits immediately (line 62)

#### Slash Commands (`handle_slash_command`, line 66)

| Command | Effect |
|---------|--------|
| `/exit`, `/quit` | Exit the program |
| `/clear` | Reset conversation history |
| `/help` | Show help text via `display.show_help()` |

Returns `True` if the command signals exit, `False` otherwise.

#### Main Flow (`main`, line 86)

```
1. Parse arguments, resolve working directory
2. Check for API key:
   - If ANTHROPIC_API_KEY is set → use it
   - If ANTHROPIC_BASE_URL is set (no key) → use api_key="dummy" (proxy mode)
   - Neither → show error, exit
3. Initialize anthropic.Anthropic client
4. Build system prompt
5. Show welcome banner
6. If initial prompt provided:
   - Run agent_loop() with it
   - If --no-interactive → return (one-shot mode)
7. Enter REPL loop:
   - Read input via prompt_toolkit
   - Handle Ctrl+C (continue), Ctrl+D (exit)
   - Handle slash commands
   - Run agent_loop() with user input
   - Loop
```

**Proxy mode:** The `api_key="dummy"` fallback (line 112) supports setups where an API proxy (like LiteLLM) handles authentication. The user sets `ANTHROPIC_BASE_URL` to the proxy endpoint and doesn't need a real API key.

---

### Step 7: Installation (`install.sh`)

**Why it exists:** Users need a way to install the agent and run it from anywhere. This script handles Python detection, dependency installation, and creates a global `coding-agent` command.

**What it does:**

```
1. Find a suitable Python 3 (tries /usr/bin/python3, /usr/local/bin/python3, $(which python3))
   - Validates Python is 3.8+
   - Checks if pip is available

2. Install dependencies from requirements.txt (if not already present)
   - Uses pip install --user

3. Create wrapper script at ~/.local/bin/coding-agent:
   #!/bin/bash
   cd <project_directory>
   python3 agent.py "$@"

4. Add ~/.local/bin to PATH:
   - Appends to ~/.zshrc or ~/.bashrc if not already present

5. Print usage examples
```

The wrapper script changes to the project directory before running `agent.py`, so the agent's own source files are always findable regardless of where the user invokes the command.

---

## 4. Key Design Decisions

### Why Exact-String Editing Over Line-Number Editing

The `edit_file` tool uses exact string matching (`old_string` → `new_string`) rather than line-number-based editing. Reasons:

1. **Robustness to context drift.** In a long session, line numbers change as files are edited. The model would need to re-read files constantly to get current line numbers. Exact strings don't depend on position.

2. **Unambiguous intent.** When the model specifies the exact text to replace, both the human reviewer (in the confirmation prompt) and the code can verify the change is correct. Line numbers are opaque — you can't tell what's being changed without reading the file.

3. **Safety.** If the target string isn't found (typo, stale context), the edit fails loudly rather than silently modifying the wrong line. If the string appears multiple times and `replace_all` isn't set, it also fails — preventing accidental mass changes.

### Why Two-Tier Models (Opus for Reasoning, Sonnet for Summarization)

The main loop uses `claude-opus-4-6` (the most capable model) for all reasoning and tool use. But summarization uses `claude-sonnet-4-20250514` (a faster, cheaper model). Why:

1. **Summarization is simple.** It just needs to compress a conversation into key facts. This doesn't require Opus-level reasoning.

2. **Cost.** Opus is significantly more expensive per token. Summarization processes the entire conversation history — potentially hundreds of thousands of tokens. Using Sonnet for this keeps costs reasonable.

3. **Speed.** Summarization happens inline (the user is waiting). Sonnet responds faster, reducing the pause.

### Why Sandbox Uses `os.path.realpath()` (Symlink Defense)

The sandbox check resolves paths with `os.path.realpath()` before checking if they're within the working directory. This catches symlink-based escapes:

```
# Without realpath:
working_dir = "/home/user/project"
path = "/home/user/project/link_to_etc"  # symlink → /etc
# Passes prefix check! But actually accesses /etc

# With realpath:
resolved = os.path.realpath(path)  # → "/etc"
# Fails prefix check. Blocked.
```

This is a deliberate security measure. The model could be tricked (via prompt injection in a file it reads) into following a symlink outside the sandbox.

### Why Tool Results Are Sent as `role: "user"` Messages

After the model calls tools, the results are sent back as a message with `role: "user"` containing `tool_result` content blocks. This is how the Claude API expects tool results — they must come from the "user" side of the conversation. Each `tool_result` block references the `tool_use_id` from the corresponding tool call.

This is an API requirement, not a design choice. But it has a useful consequence: the conversation always alternates user/assistant, which keeps the message structure clean for context management and summarization.

### Why Manual Stream Event Parsing Instead of SDK Helpers

The loop processes raw stream events (`content_block_start`, `content_block_delta`, etc.) rather than using SDK convenience methods like `stream.text`. Reasons:

1. **Interleaved content.** A single response can contain multiple content blocks — some text, some tool calls — interleaved in any order. Manual parsing handles this naturally.

2. **Live rendering.** Text deltas need to be displayed immediately as they arrive. SDK helpers that buffer the full response would delay display.

3. **Tool input accumulation.** Tool call inputs arrive as JSON fragments across multiple `input_json_delta` events. They need to be concatenated and parsed only when the block ends. Manual parsing makes this explicit and reliable.

4. **Cancel handling.** On Ctrl+C, the code needs to capture whatever partial content has arrived. With manual parsing, this is straightforward — the buffer is always available.

---

## 5. Safety & Security Model

### File Sandbox Enforcement

Every file operation (read, write, edit, glob, grep, list) goes through the sandbox check:

```
User-provided path
  → _resolve_path(): join with working_dir if relative, then os.path.realpath()
  → _check_within_sandbox(): verify resolved path starts with working_dir
  → Proceed only if within sandbox
```

This prevents:
- Reading sensitive files outside the project (e.g., `~/.ssh/id_rsa`)
- Writing files outside the project
- Symlink-based escapes (resolved before checking)
- Path traversal attacks (e.g., `../../etc/passwd` — resolved to absolute path first)

### Confirmation Prompt System

Three tiers of tool approval:

| Tier | Tools | Behavior |
|------|-------|----------|
| **Auto-approve** | `read_file`, `glob_search`, `grep_search`, `list_directory` | Always run — read-only, no risk |
| **Safe whitelist** | `bash` with safe prefix (28 commands) | Always run — known-safe commands |
| **User confirmation** | `write_file`, `edit_file`, unsafe `bash` | Prompt user with y/n before executing |

The `--auto-approve` flag bypasses all confirmation prompts, which is useful for scripted/non-interactive use but should be used with caution.

### Bash Timeout

Every shell command has a **120-second default timeout** (`timeout` parameter in the `bash` tool schema, default value 120). If a command exceeds this timeout, `subprocess.run()` raises `subprocess.TimeoutExpired`, which is caught and returned as an error message.

This prevents:
- Runaway processes (infinite loops, hanging network calls)
- Resource exhaustion
- The agent appearing to freeze

The model can override the timeout by passing a different `timeout` value in the tool input, but 120 seconds is the default safety net.

### Max Iteration Limit

`MAX_ITERATIONS = 50` in `loop.py`. If the model makes 50 consecutive API calls with tool use without stopping, the loop terminates with an error message.

This prevents:
- Infinite tool-calling loops (model gets stuck in a cycle)
- Unbounded API cost accumulation
- Runaway file modifications

50 iterations is generous enough for complex tasks (reading many files, running multiple commands) but catches genuine loops.
