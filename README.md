# Recall — Cross-Project Session Manager for Claude Code

Recall solves a core limitation of Claude Code: **conversation history is isolated per project directory**. Whether you use VS Code, JetBrains, or the terminal CLI, you cannot see or resume sessions from other projects.

Recall provides a **centralized session management hub** with category-based organization, allowing you to save, browse, load, and resume conversations across all your projects.

## Features

| Command | Description |
|---------|-------------|
| `/recall` | Show action menu |
| `/recall save` | Save current session to central directory |
| `/recall list` | List all saved sessions across projects |
| `/recall load` | Load a past session as reference context |
| `/recall resume` | Find and resume a session from any project |
| `/recall rename` | Rename a session (syncs with original project) |
| `/recall move` | Move session to a different category |
| `/recall manage` | Add/remove/view categories |

## How It Works

```
D:\claude-sessions\          ← Central directory (configurable)
├── _config.json             ← Categories & settings
├── 代码/
│   ├── MyProject_meta.json  ← Metadata + mapping to original
│   └── MyProject.jsonl      ← Full session backup
├── 论文/
├── 学习/
└── ...
```

- **Save**: Copies the session `.jsonl` + creates `_meta.json` pointing to the original file
- **List**: Scans all categories, shows sessions in a table (name, project, date, message count)
- **Load Context**: Extracts key messages (user + assistant text) and injects them as reference into your current conversation — great for cross-project knowledge transfer
- **Resume**: Locates the original session file and guides you to restore it with `/resume`
- **Rename**: Bidirectional sync — updates both the central index and the original project's session metadata

## Installation

### From Skills CLI

```bash
npx skills add 24kchengYe/recall
```

### Manual Installation

Clone this repo into your Claude Code skills directory:

```bash
git clone https://github.com/24kchengYe/recall.git ~/.claude/skills/recall
```

Or on Windows:

```bash
git clone https://github.com/24kchengYe/recall.git %USERPROFILE%\.claude\skills\recall
```

## Requirements

- Claude Code (any IDE or CLI)
- Python 3.8+ (for the helper script that parses session files)

## Configuration

On first `/recall save`, Recall initializes:
- **Default storage path**: `D:\claude-sessions\` (you'll be asked to confirm or change)
- **Default categories**: 学习, 生活, 代码, 算法, 论文, 工作, 杂项

You can customize the base path and categories in `D:\claude-sessions\_config.json`.

## Why Recall?

- You work on multiple projects but want to reference past conversations
- You discussed an algorithm in Project A and need that context in Project B
- You want to organize conversations by topic (research, coding, learning) rather than by project directory
- You want a backup of important conversations in one central place

## License

MIT
