---
name: recall
description: |
  Cross-project session management hub for Claude Code. Use this skill when the user wants to
  manage conversations across different projects and directories.

  Trigger on /recall command or these specific phrases:
  - "/recall", "/recall save", "/recall list", "/recall load", "/recall resume", "/recall rename", "/recall move", "/recall manage"
  - "recall save", "recall list", "recall load", "recall resume", "recall rename", "recall move"
  - "recall 保存", "recall 列出", "recall 加载", "recall 恢复", "recall 重命名", "recall 移动"

  Do NOT trigger on generic phrases like "save session" or "保存会话" alone — only when "recall" is explicitly mentioned or /recall is used.
---

# Recall — Cross-Project Session Management Hub

Recall is a centralized session management system for Claude Code. It solves the problem that Claude Code isolates conversation history by project directory — you cannot see or resume sessions from other projects. Recall provides a central index with category-based organization.

## Architecture

**Central directory = Management index layer (mapping + categorization)**

- The central directory (default: `D:\claude-sessions\`) stores metadata + backup copies of sessions
- Each session has a `_meta.json` (pointing to the original file) and a `.jsonl` backup
- Sessions are organized into user-defined categories (学习, 代码, 论文, etc.)
- Rename syncs bidirectionally: both the central index and the original project's sessions-index.json

## Important Notes

- This skill is **independent** from Claude Code's built-in `/resume` and `/rename` commands
- Built-in `/resume` only shows current project sessions; Recall shows ALL projects
- Always use `AskUserQuestion` to confirm user intent before executing any operation
- All file paths must handle Windows paths correctly (backslashes, Chinese characters, spaces)

## Configuration

**Config file**: `{basePath}/_config.json`

```json
{
  "version": 1,
  "basePath": "D:\\claude-sessions",
  "categories": ["学习", "生活", "代码", "算法", "论文", "工作", "杂项"],
  "created": "2026-03-01T00:00:00Z"
}
```

**Meta file**: `{basePath}/{category}/{name}_meta.json`

```json
{
  "sessionId": "UUID",
  "name": "user-defined name",
  "category": "论文",
  "originalProject": "G:\\Research_20250121\\...",
  "originalProjectDir": "G--Research-20250121-12--...",
  "originalSessionFile": "C:\\Users\\ASUS\\.claude\\projects\\...\\uuid.jsonl",
  "backupFile": "D:\\claude-sessions\\论文\\name.jsonl",
  "created": "ISO 8601",
  "saved": "ISO 8601",
  "modified": "ISO 8601",
  "messageCount": 42,
  "firstPrompt": "first message preview...",
  "summary": "session summary",
  "tags": []
}
```

## Command Routing

Parse the ARGUMENTS value to determine which command to execute:

- No arguments or empty → **Entry Menu**
- `save` → **Save Session**
- `list` → **List Sessions**
- `load` → **Load Context**
- `resume` → **Resume Session**
- `rename` → **Rename Session**
- `move` → **Move Category**
- `manage` → **Manage Categories**

If ARGUMENTS doesn't match any command, treat it as a natural language query and infer the closest command, then confirm with the user.

---

## Entry Menu (`/recall` with no arguments)

Use `AskUserQuestion` to present all available operations:

```
question: "Recall — 你想执行什么操作？"
options:
  - "save — 保存当前会话到中央目录"
  - "list — 列出所有已保存的会话"
  - "load — 加载历史会话作为参考上下文"
  - "resume — 从中央目录恢复一个会话"
  - "rename — 重命名已保存的会话"
  - "move — 移动会话到其他类别"
  - "manage — 管理类别（增删、统计）"
```

---

## Command 1: Save Session (`/recall save`)

### Workflow

1. **Initialize config** (if first run):
   - Check if `D:\claude-sessions\_config.json` exists
   - If not, use `AskUserQuestion` to ask user for the base path (default: `D:\claude-sessions`)
   - Create directory structure: base dir + all default category subdirs
   - Write `_config.json`

2. **Find current session**:
   - Determine current working directory (use `pwd` via Bash)
   - Convert to Claude projects directory name:
     - Replace `:` with empty, `\` or `/` with `--`
     - Example: `G:\Research_20250121\...` → `G--Research-20250121-...`
   - Read `C:\Users\ASUS\.claude\projects\{projectDir}\sessions-index.json`
   - Find the entry with the most recent `modified` timestamp (this is the current session)

3. **Get user input** via `AskUserQuestion`:
   - **Session name**: Default to the `summary` field from sessions-index. Let user type a custom name via "Other" option.
   - **Category**: Show existing categories from `_config.json` + "新建类别" option

4. **Execute save**:
   - If user chose a new category: create the subdirectory and update `_config.json`
   - Copy the `.jsonl` file to `{basePath}/{category}/{name}.jsonl` using Bash `cp`
   - Create `{basePath}/{category}/{name}_meta.json` with all metadata
   - Report success with the save location

### Key Details

- Sanitize the session name for use as filename (replace special chars)
- If a file with the same name already exists in that category, ask user whether to overwrite or use a different name
- Store the current timestamp as `saved`, preserve original `created` and `modified`

---

## Command 2: List Sessions (`/recall list`)

### Workflow

1. Read `_config.json` to get basePath and categories
2. Use `AskUserQuestion` to let user choose:
   - A specific category to browse
   - Or "全部 — 所有类别" to see everything
3. Scan `_meta.json` files in the chosen category (or all categories) using Glob
4. Read each `_meta.json` and collect metadata
5. Display as a formatted table sorted by `modified` (newest first):

```
| # | 名称 | 类别 | 来源项目 | 消息数 | 最后修改 | 预览 |
|---|------|------|----------|--------|----------|------|
| 1 | BSAS论文修改 | 论文 | G:\Research... | 42 | 2026-02-28 | 首先Expert Rubrics... |
| 2 | Python调试 | 代码 | D:\python... | 15 | 2026-02-27 | 帮我看一下这个bug... |
```

6. After showing the table, ask user if they want to perform an action on any session (load, resume, rename, move)

---

## Command 3: Load Context (`/recall load`)

### Workflow

1. List sessions (same as list command, abbreviated)
2. Let user select one or more sessions to load
3. Ask user for extraction detail level:
   - **精简模式 (brief)**: Only user questions + assistant text answers
   - **详细模式 (detailed)**: Also includes tool names and key parameters (file paths, commands)
4. For each selected session, run the Python helper:
   ```bash
   python "C:\Users\ASUS\.claude\skills\recall\scripts\session_utils.py" extract "{backupFile}" --mode brief|detailed --max-messages 30
   ```
5. Present the extracted content clearly:
   ```
   --- 参考会话: {name} ({category}) ---
   [User] 首先 Expert Rubrics 两个词感觉有点冗余...
   [Assistant] 你说得对，我建议改为 Rule Learning...
   ...
   --- 参考会话结束 ---
   ```
6. Tell the user: "以上历史会话内容已加载为参考。你可以继续当前对话，我会参考这些上下文。"

---

## Command 4: Resume Session (`/recall resume`)

### Workflow

1. List sessions (same as list command)
2. User selects a session to resume
3. Read the session's `_meta.json` to get `originalSessionFile` and `originalProject`
4. Check if the original file still exists (use Bash `test -f`)
5. **If original exists**:
   - Tell user: "该会话来自项目: `{originalProject}`"
   - Tell user: "请在该项目目录下打开 Claude Code，然后使用 `/resume` 恢复会话"
   - Provide the session ID for reference
6. **If original is missing**:
   - Inform user the original was deleted but backup exists
   - Ask if they want to restore: copy backup `.jsonl` back to the Claude projects directory
   - If yes: copy file, update `sessions-index.json` in the target project directory
   - Tell user they can now `/resume` in that project

---

## Command 5: Rename Session (`/recall rename`)

### Workflow

1. List sessions, user selects one to rename
2. Show current name, ask for new name via `AskUserQuestion`
3. **Bidirectional sync**:
   a. Update `_meta.json`: change `name` and `summary` fields
   b. Rename files in central directory:
      - `{old_name}_meta.json` → `{new_name}_meta.json`
      - `{old_name}.jsonl` → `{new_name}.jsonl`
      - Update `backupFile` path in meta
   c. Update original project's `sessions-index.json`:
      - Read the file at `C:\Users\ASUS\.claude\projects\{originalProjectDir}\sessions-index.json`
      - Find the entry matching `sessionId`
      - Update its `summary` field to the new name
      - Write back the file
4. Confirm success

---

## Command 6: Move Category (`/recall move`)

### Workflow

1. List sessions, user selects one to move
2. Show current category and available target categories (+ "新建类别" option)
3. If new category: create directory, update `_config.json`
4. Move files:
   ```bash
   mv "{basePath}/{oldCategory}/{name}_meta.json" "{basePath}/{newCategory}/{name}_meta.json"
   mv "{basePath}/{oldCategory}/{name}.jsonl" "{basePath}/{newCategory}/{name}.jsonl"
   ```
5. Update `_meta.json`: change `category` and `backupFile` fields
6. Confirm success

---

## Command 7: Manage Categories (`/recall manage`)

### Workflow

1. Read `_config.json` and scan each category directory
2. Display category stats:
   ```
   | 类别 | 会话数 |
   |------|--------|
   | 学习 | 3 |
   | 代码 | 7 |
   | 论文 | 2 |
   | 生活 | 0 |
   ```
3. Ask user what they want to do:
   - **添加类别**: Enter new category name → create dir + update config
   - **删除空类别**: Only allow deleting categories with 0 sessions → remove dir + update config
   - **返回**: Go back

---

## Helper Script Reference

The Python helper script is located at:
`C:\Users\ASUS\.claude\skills\recall\scripts\session_utils.py`

### Usage

```bash
# Extract readable content from a session
python session_utils.py extract <jsonl_path> [--mode brief|detailed] [--max-messages 30] [--max-chars 500]

# List all sessions in the central directory
python session_utils.py list <base_dir> [--category <name>]

# Check if original session files still exist
python session_utils.py check <base_dir>
```

### When to use the helper vs. direct tools

- **Use helper for**: Extracting session content (parsing large JSONL efficiently)
- **Use direct tools for**: Reading/writing meta.json, copying files, reading config (simpler operations)

---

## Path Conversion Reference

To convert a project path to its Claude projects directory name:

```
Input:  G:\Research_20250121\12建筑尺度城市分析和模拟（aum+bs）\投稿\building simulation
Output: G--Research-20250121-12------------aum-bs-----building-simulation
```

Rules:
1. Remove the colon after drive letter
2. Replace `\` and `/` with `--`
3. Non-ASCII characters and special chars are converted (parentheses, plus, spaces become dashes)

The safest approach: use Bash to `ls` the `C:\Users\ASUS\.claude\projects\` directory and find the matching project dir by checking which one's `sessions-index.json` contains `projectPath` matching the current `pwd`.
