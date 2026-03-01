#!/usr/bin/env python3
"""
Recall Session Utils — Helper script for cross-project session management.

Subcommands:
  extract  - Extract readable content from a session .jsonl file
  list     - List all saved sessions in the central directory
  check    - Verify that original session files still exist
"""

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows terminal encoding for Chinese characters
if platform.system() == "Windows" or "MSYS" in os.environ.get("MSYSTEM", ""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _normalize_path(path_str: str) -> str:
    """Convert MSYS-style paths (/c/Users/...) to Windows paths (C:\\Users\\...) if needed."""
    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
        drive_letter = path_str[1].upper()
        return f"{drive_letter}:{path_str[2:]}".replace("/", "\\")
    return path_str


def extract_session(jsonl_path: str, mode: str = "brief", max_messages: int = 30, max_chars: int = 500) -> str:
    """Extract readable conversation content from a session .jsonl file.

    Args:
        jsonl_path: Path to the .jsonl session file
        mode: 'brief' (user + assistant text only) or 'detailed' (includes tool info)
        max_messages: Maximum number of messages to extract
        max_chars: Maximum characters per message
    """
    path = Path(_normalize_path(jsonl_path))
    if not path.exists():
        return f"Error: File not found: {jsonl_path}"

    messages = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                msg = entry.get("message", {})

                if entry_type == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                        # Skip tool_result entries (they appear as user messages)
                        if not text.startswith("{") and "tool_use_id" not in text:
                            messages.append(("User", _truncate(text, max_chars)))
                    elif isinstance(content, list):
                        # Extract text parts, skip tool_result parts
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif part.get("type") == "tool_result" and mode == "detailed":
                                    # In detailed mode, show a brief note about tool results
                                    tool_content = part.get("content", "")
                                    if isinstance(tool_content, str) and len(tool_content) > 0:
                                        preview = _truncate(tool_content, 100)
                                        text_parts.append(f"[Tool Result: {preview}]")
                        combined = "\n".join(text_parts).strip()
                        if combined:
                            messages.append(("User", _truncate(combined, max_chars)))

                elif entry_type == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("Assistant", _truncate(content.strip(), max_chars)))
                    elif isinstance(content, list):
                        text_parts = []
                        tool_notes = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif part.get("type") == "tool_use" and mode == "detailed":
                                    tool_name = part.get("name", "unknown")
                                    tool_input = part.get("input", {})
                                    # Extract key info based on tool type
                                    note = _summarize_tool_use(tool_name, tool_input)
                                    if note:
                                        tool_notes.append(note)
                                # Skip 'thinking' blocks entirely
                        combined = "\n".join(text_parts).strip()
                        if tool_notes:
                            combined += "\n" + "\n".join(f"  [{note}]" for note in tool_notes)
                        if combined:
                            messages.append(("Assistant", _truncate(combined, max_chars)))

    except Exception as e:
        return f"Error reading file: {e}"

    if not messages:
        return "No readable messages found in session."

    # Limit to max_messages
    if len(messages) > max_messages:
        messages = messages[:max_messages]

    # Format output
    output_lines = []
    for role, text in messages:
        output_lines.append(f"[{role}] {text}")
        output_lines.append("")  # blank line between messages

    return "\n".join(output_lines)


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _summarize_tool_use(tool_name: str, tool_input: dict) -> str:
    """Create a brief summary of a tool use for detailed mode."""
    if tool_name in ("Read", "Glob", "Grep"):
        path = tool_input.get("file_path", "") or tool_input.get("path", "") or tool_input.get("pattern", "")
        return f"Tool: {tool_name} → {path}" if path else f"Tool: {tool_name}"
    elif tool_name == "Edit":
        path = tool_input.get("file_path", "")
        return f"Tool: Edit → {path}" if path else "Tool: Edit"
    elif tool_name == "Write":
        path = tool_input.get("file_path", "")
        return f"Tool: Write → {path}" if path else "Tool: Write"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd:
            return f"Tool: Bash → {_truncate(cmd, 80)}"
        return "Tool: Bash"
    elif tool_name == "Agent":
        desc = tool_input.get("description", "")
        return f"Tool: Agent → {desc}" if desc else "Tool: Agent"
    else:
        return f"Tool: {tool_name}"


def list_sessions(base_dir: str, category: str = None) -> str:
    """List all saved sessions in the central directory.

    Args:
        base_dir: Path to the central sessions directory
        category: Optional category filter
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    config_path = base_path / "_config.json"
    if not config_path.exists():
        return "Error: _config.json not found. Run /recall save first to initialize."

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        return f"Error reading config: {e}"

    categories = [category] if category else config.get("categories", [])
    sessions = []

    for cat in categories:
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                sessions.append(meta)
            except Exception:
                continue

    if not sessions:
        if category:
            return f"No sessions found in category: {category}"
        return "No sessions saved yet."

    # Sort by modified time (newest first)
    sessions.sort(key=lambda s: s.get("modified", ""), reverse=True)

    # Format as table
    lines = []
    lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12} {'来源项目':<30}")
    lines.append("-" * 90)

    for i, s in enumerate(sessions, 1):
        name = _truncate(s.get("name", "unnamed"), 24)
        cat = s.get("category", "?")
        count = s.get("messageCount", "?")
        modified = s.get("modified", "?")
        if isinstance(modified, str) and len(modified) >= 10:
            modified = modified[:10]
        project = s.get("originalProject", "?")
        # Shorten project path
        if len(project) > 29:
            project = "..." + project[-26:]
        lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12} {project:<30}")

    return "\n".join(lines)


def check_sessions(base_dir: str) -> str:
    """Check if original session files still exist for all saved sessions.

    Args:
        base_dir: Path to the central sessions directory
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    config_path = base_path / "_config.json"
    if not config_path.exists():
        return "Error: _config.json not found."

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        return f"Error reading config: {e}"

    categories = config.get("categories", [])
    results = {"ok": [], "missing": [], "error": []}

    for cat in categories:
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                name = meta.get("name", "unnamed")
                original = meta.get("originalSessionFile", "")
                if original and Path(original).exists():
                    results["ok"].append(f"  OK: {name} ({cat}) → {original}")
                else:
                    results["missing"].append(f"  MISSING: {name} ({cat}) → {original}")
            except Exception as e:
                results["error"].append(f"  ERROR: {meta_file.name} → {e}")

    lines = []
    total = len(results["ok"]) + len(results["missing"]) + len(results["error"])
    lines.append(f"Checked {total} sessions:")
    lines.append(f"  ✓ {len(results['ok'])} OK")
    lines.append(f"  ✗ {len(results['missing'])} missing original")
    lines.append(f"  ! {len(results['error'])} errors")

    if results["missing"]:
        lines.append("\nMissing originals (backup copies still available):")
        lines.extend(results["missing"])

    if results["error"]:
        lines.append("\nErrors:")
        lines.extend(results["error"])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Recall Session Utils")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract readable content from a session")
    extract_parser.add_argument("jsonl_path", help="Path to the .jsonl session file")
    extract_parser.add_argument("--mode", choices=["brief", "detailed"], default="brief",
                                help="Extraction mode (default: brief)")
    extract_parser.add_argument("--max-messages", type=int, default=30,
                                help="Maximum messages to extract (default: 30)")
    extract_parser.add_argument("--max-chars", type=int, default=500,
                                help="Maximum characters per message (default: 500)")

    # list subcommand
    list_parser = subparsers.add_parser("list", help="List saved sessions")
    list_parser.add_argument("base_dir", help="Path to the central sessions directory")
    list_parser.add_argument("--category", help="Filter by category")

    # check subcommand
    check_parser = subparsers.add_parser("check", help="Check original file existence")
    check_parser.add_argument("base_dir", help="Path to the central sessions directory")

    args = parser.parse_args()

    if args.command == "extract":
        print(extract_session(args.jsonl_path, args.mode, args.max_messages, args.max_chars))
    elif args.command == "list":
        print(list_sessions(args.base_dir, args.category))
    elif args.command == "check":
        print(check_sessions(args.base_dir))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
