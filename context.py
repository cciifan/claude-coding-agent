"""Conversation context management with summarization."""

import anthropic

# Rough estimate: ~4 chars per token
CHARS_PER_TOKEN = 4
# Summarize when we estimate we're approaching this many tokens
MAX_CONTEXT_TOKENS = 150_000
# Keep the most recent N messages verbatim
RECENT_MESSAGES_TO_KEEP = 20


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate the total token count of a message list."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # Text block
                    if "text" in block:
                        total_chars += len(block["text"])
                    # Tool result block
                    elif "content" in block:
                        if isinstance(block["content"], str):
                            total_chars += len(block["content"])
                        elif isinstance(block["content"], list):
                            for sub in block["content"]:
                                if isinstance(sub, dict) and "text" in sub:
                                    total_chars += len(sub["text"])
                    # Tool use block
                    elif "input" in block:
                        total_chars += len(str(block["input"]))
    return total_chars // CHARS_PER_TOKEN


def needs_summarization(messages: list[dict]) -> bool:
    """Check if the conversation is approaching the context limit."""
    return estimate_tokens(messages) > MAX_CONTEXT_TOKENS


def summarize_conversation(
    client: anthropic.Anthropic, messages: list[dict]
) -> list[dict]:
    """Summarize older messages to reduce context size.

    Keeps the most recent messages verbatim and summarizes the rest.
    Returns a new message list starting with the summary.
    """
    if len(messages) <= RECENT_MESSAGES_TO_KEEP:
        return messages

    older = messages[:-RECENT_MESSAGES_TO_KEEP]
    recent = messages[-RECENT_MESSAGES_TO_KEEP:]

    # Build a text representation of older messages for summarization
    summary_parts = []
    for msg in older:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            summary_parts.append(f"{role}: {content[:2000]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        summary_parts.append(f"{role}: {block['text'][:2000]}")
                    elif block.get("type") == "tool_use":
                        summary_parts.append(
                            f"{role}: [tool_use: {block.get('name', '?')}]"
                        )
                    elif block.get("type") == "tool_result":
                        result_text = block.get("content", "")
                        if isinstance(result_text, str):
                            summary_parts.append(
                                f"{role}: [tool_result: {result_text[:500]}]"
                            )

    conversation_text = "\n".join(summary_parts)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this conversation history concisely. "
                        "Focus on: what the user asked for, what files were read/modified, "
                        "what commands were run, and key decisions made. "
                        "Be brief but preserve important context.\n\n"
                        f"{conversation_text}"
                    ),
                }
            ],
        )
        summary_text = response.content[0].text
    except Exception:
        # If summarization fails, just truncate
        summary_text = (
            "(Earlier conversation was truncated to save context space. "
            "Recent messages are preserved below.)"
        )

    # Build new message list with summary + recent messages
    summarized = [
        {
            "role": "user",
            "content": f"[Previous conversation summary: {summary_text}]",
        },
        {
            "role": "assistant",
            "content": "Understood. I have the context from our earlier conversation. How can I help?",
        },
    ]
    summarized.extend(recent)
    return summarized
