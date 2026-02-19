#!/usr/bin/env bash
# Install the coding agent and make it available as 'coding-agent' globally.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

# Find a python3 that can import the dependencies (or install them).
# Try common locations; pick the first one where pip works.
PYTHON=""
for candidate in /usr/bin/python3 /usr/local/bin/python3 "$(which python3 2>/dev/null)"; do
    [ -x "$candidate" ] || continue
    if "$candidate" -c "import anthropic, rich, prompt_toolkit" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
    if "$candidate" -m pip --version 2>/dev/null | grep -q pip; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Could not find a usable python3 with pip."
    echo "Install Python 3.8+ with pip and try again."
    exit 1
fi

echo "Using python: $PYTHON ($("$PYTHON" --version 2>&1))"

# Install deps if not already present
if ! "$PYTHON" -c "import anthropic, rich, prompt_toolkit" 2>/dev/null; then
    echo "Installing dependencies..."
    "$PYTHON" -m pip install -q -r "$DIR/requirements.txt"
else
    echo "Dependencies already installed."
fi

# Create wrapper script
echo "Creating 'coding-agent' command..."
WRAPPER="$HOME/.local/bin/coding-agent"
mkdir -p "$HOME/.local/bin"

cat > "$WRAPPER" << EOF
#!/usr/bin/env bash
exec $PYTHON "$DIR/agent.py" "\$@"
EOF

chmod +x "$WRAPPER"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    SHELL_RC="$HOME/.zshrc"
    [[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    echo "Added ~/.local/bin to PATH in $SHELL_RC — restart your shell or run:"
    echo "  source $SHELL_RC"
fi

echo ""
echo "Done! Usage:"
echo "  coding-agent                          # interactive mode"
echo "  coding-agent \"your prompt here\"       # one-shot mode"
echo "  coding-agent -d ~/project             # work in a specific directory"
echo "  coding-agent --auto-approve           # skip confirmations"
