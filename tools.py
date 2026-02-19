"""Tool definitions and executors for the coding agent."""

from __future__ import annotations

import fnmatch
import glob
import os
import re
import subprocess

# ── JSON Schemas ──────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Returns the file text with line numbers. "
            "Use offset and limit to read specific portions of large files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based). Defaults to 1.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Defaults to all.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file, creating it if it doesn't exist or overwriting if it does. "
            "Parent directories are created automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing an exact string match with new content. "
            "The old_string must match exactly (including whitespace and indentation). "
            "Use replace_all=true to replace every occurrence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit.",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement string.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace all occurrences. Default false.",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Execute a shell command and return its stdout and stderr. "
            "Commands run in the current working directory. "
            "Use this for running programs, git operations, installing packages, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default 120.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "glob_search",
        "description": (
            "Find files matching a glob pattern. Returns a list of matching file paths "
            "relative to the search directory. Example patterns: '**/*.py', 'src/**/*.ts'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files against.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in. Defaults to current working directory.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": (
            "Search file contents using a regular expression. Returns matching lines "
            "with file paths and line numbers. Searches recursively in the given directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in. Defaults to current working directory.",
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter which files to search (e.g. '*.py').",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_directory",
        "description": (
            "List the contents of a directory. Returns file and directory names "
            "with type indicators (file/dir) and sizes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list. Defaults to current working directory.",
                },
            },
            "required": [],
        },
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_path(path: str, working_dir: str) -> str:
    """Resolve a path relative to the working directory."""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(working_dir, path))


def _check_within_sandbox(resolved: str, working_dir: str) -> str | None:
    """Return an error string if path is outside the sandbox, else None."""
    real_resolved = os.path.realpath(resolved)
    real_working = os.path.realpath(working_dir)
    if not real_resolved.startswith(real_working + os.sep) and real_resolved != real_working:
        return f"Error: Path '{resolved}' is outside the working directory '{working_dir}'."
    return None


# ── Executors ─────────────────────────────────────────────────────────────────

def execute_read_file(params: dict, working_dir: str) -> str:
    """Read a file's contents with optional offset and limit."""
    file_path = _resolve_path(params["file_path"], working_dir)
    sandbox_err = _check_within_sandbox(file_path, working_dir)
    if sandbox_err:
        return sandbox_err

    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"
    if os.path.isdir(file_path):
        return f"Error: '{file_path}' is a directory, not a file."

    try:
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading file: {e}"

    offset = max(params.get("offset", 1), 1)
    limit = params.get("limit")

    selected = lines[offset - 1:]
    if limit is not None:
        selected = selected[:limit]

    numbered = []
    for i, line in enumerate(selected, start=offset):
        numbered.append(f"{i:>6}\t{line.rstrip()}")

    if not numbered:
        return "(empty file)"
    return "\n".join(numbered)


def execute_write_file(params: dict, working_dir: str) -> str:
    """Write content to a file."""
    file_path = _resolve_path(params["file_path"], working_dir)
    sandbox_err = _check_within_sandbox(file_path, working_dir)
    if sandbox_err:
        return sandbox_err

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(params["content"])
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def execute_edit_file(params: dict, working_dir: str) -> str:
    """Edit a file by replacing old_string with new_string."""
    file_path = _resolve_path(params["file_path"], working_dir)
    sandbox_err = _check_within_sandbox(file_path, working_dir)
    if sandbox_err:
        return sandbox_err

    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"

    try:
        with open(file_path, "r") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading file: {e}"

    old_string = params["old_string"]
    new_string = params["new_string"]
    replace_all = params.get("replace_all", False)

    if old_string not in content:
        return f"Error: old_string not found in {file_path}."

    if not replace_all:
        count = content.count(old_string)
        if count > 1:
            return (
                f"Error: old_string appears {count} times in {file_path}. "
                f"Provide more context to make it unique, or set replace_all=true."
            )
        new_content = content.replace(old_string, new_string, 1)
    else:
        new_content = content.replace(old_string, new_string)

    try:
        with open(file_path, "w") as f:
            f.write(new_content)
        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def execute_bash(params: dict, working_dir: str) -> str:
    """Execute a shell command."""
    command = params["command"]
    timeout = params.get("timeout", 120)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        if result.returncode != 0:
            output_parts.append(f"Exit code: {result.returncode}")
        return "\n".join(output_parts) if output_parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error executing command: {e}"


def execute_glob_search(params: dict, working_dir: str) -> str:
    """Find files matching a glob pattern."""
    pattern = params["pattern"]
    search_dir = _resolve_path(params.get("path", "."), working_dir)

    sandbox_err = _check_within_sandbox(search_dir, working_dir)
    if sandbox_err:
        return sandbox_err

    full_pattern = os.path.join(search_dir, pattern)
    matches = sorted(glob.glob(full_pattern, recursive=True))

    # Filter out directories, keep only files
    matches = [m for m in matches if os.path.isfile(m)]

    if not matches:
        return "No files matched the pattern."

    # Make paths relative to working dir for cleaner output
    relative = []
    for m in matches[:200]:  # Cap at 200 results
        try:
            relative.append(os.path.relpath(m, working_dir))
        except ValueError:
            relative.append(m)

    result = "\n".join(relative)
    if len(matches) > 200:
        result += f"\n... and {len(matches) - 200} more files"
    return result


def execute_grep_search(params: dict, working_dir: str) -> str:
    """Search file contents with regex."""
    pattern = params["pattern"]
    search_path = _resolve_path(params.get("path", "."), working_dir)
    include = params.get("include")

    sandbox_err = _check_within_sandbox(search_path, working_dir)
    if sandbox_err:
        return sandbox_err

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results = []
    max_results = 200

    def search_file(fpath: str):
        try:
            with open(fpath, "r", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    if len(results) >= max_results:
                        return
                    if regex.search(line):
                        rel = os.path.relpath(fpath, working_dir)
                        results.append(f"{rel}:{line_num}: {line.rstrip()}")
        except (OSError, UnicodeDecodeError):
            pass

    if os.path.isfile(search_path):
        search_file(search_path)
    else:
        for root, dirs, files in os.walk(search_path):
            # Skip hidden dirs and common noise
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
            for fname in files:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                if len(results) >= max_results:
                    break
                search_file(os.path.join(root, fname))

    if not results:
        return "No matches found."
    output = "\n".join(results)
    if len(results) >= max_results:
        output += f"\n... (results capped at {max_results})"
    return output


def execute_list_directory(params: dict, working_dir: str) -> str:
    """List directory contents."""
    dir_path = _resolve_path(params.get("path", "."), working_dir)

    sandbox_err = _check_within_sandbox(dir_path, working_dir)
    if sandbox_err:
        return sandbox_err

    if not os.path.exists(dir_path):
        return f"Error: Directory not found: {dir_path}"
    if not os.path.isdir(dir_path):
        return f"Error: '{dir_path}' is not a directory."

    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return f"Error: Permission denied: {dir_path}"

    lines = []
    for entry in entries:
        full = os.path.join(dir_path, entry)
        if os.path.isdir(full):
            lines.append(f"  {entry}/")
        else:
            try:
                size = os.path.getsize(full)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                lines.append(f"  {entry}  ({size_str})")
            except OSError:
                lines.append(f"  {entry}")

    if not lines:
        return "(empty directory)"
    return "\n".join(lines)


# ── Dispatcher ────────────────────────────────────────────────────────────────

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
    """Execute a tool by name and return its result string."""
    executor = EXECUTORS.get(tool_name)
    if executor is None:
        return f"Error: Unknown tool '{tool_name}'."
    try:
        return executor(tool_input, working_dir)
    except Exception as e:
        return f"Error executing {tool_name}: {e}"
