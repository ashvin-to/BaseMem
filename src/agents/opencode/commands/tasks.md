---
description: List tasks on the current project
---
List all tasks for this project. Derive the topic from the current folder name.

```
task_list(topic="<folder>")
```

If no tasks exist, suggest creating one:
```
task_create(topic="<folder>", title="Task title", priority="high")
```
