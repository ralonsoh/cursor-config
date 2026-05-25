# Task Log Skill

A Claude skill for logging and querying the personal task calendar stored in `~/.claude/tasks/`.

## File structure

- **Directory:** `~/.claude/tasks/`
- **One file per ISO week:** `~/.claude/tasks/YYYY-WNN.md`
- **Search/report script:** `~/.claude/tasks/tasks.py`

## Markdown format

```markdown
# Week NN — YYYY

## <Weekday> YYYY-MM-DD

### Task: <title>
**Description:** <description>
**Comments:** <additional comments>
**Tags:** `tag1`, `tag2`

---
```

## How to log a task (when user asks to add/log a task)

1. Determine today's ISO week: `python3 -c "from datetime import date; d=date.today(); iso=d.isocalendar(); print(f'{iso.year}-W{iso.week:02d}')"`
2. Determine today's full weekday+date: `python3 -c "from datetime import date; d=date.today(); print(d.strftime('%A %Y-%m-%d'))"`
3. Compute the week file path: `~/.claude/tasks/YYYY-WNN.md`
4. If the file does not exist, create it with the header: `# Week NN — YYYY`
5. If the day section does not exist in the file, append it: `## <Weekday> YYYY-MM-DD`
6. Append the task entry under the day section in this exact format:

```
### Task: <title>
**Description:** <description>
**Comments:** <comments or "None">
**Tags:** `tag1`, `tag2`

---
```

7. Ask the user for title, description, comments, and tags if not provided.

## How to search and report (when user asks to search or get a report)

Run the `tasks.py` script:

```bash
# Weekly summary (current week)
python3 ~/.claude/tasks/tasks.py week

# Weekly summary (specific week)
python3 ~/.claude/tasks/tasks.py week 2026-W09

# Search by keyword
python3 ~/.claude/tasks/tasks.py search <keyword>

# Tasks in a date range
python3 ~/.claude/tasks/tasks.py range YYYY-MM-DD YYYY-MM-DD

# Filter by tag
python3 ~/.claude/tasks/tasks.py tag <tagname>
```

Display the output to the user in a readable format.
