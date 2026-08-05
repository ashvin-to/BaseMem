---
name: log
description: Log a decision or fact to the current project
---

Log an interaction to the current project's memory.

For decisions:
```
logInteraction(topic="<folder-name>", decision="What was decided and why")
```

For facts:
```
logInteraction(topic="<folder-name>", fact="What is now known")
```

At session end:
```
logInteraction(topic="<folder-name>", summary="One paragraph summary.", activity="done")
```
