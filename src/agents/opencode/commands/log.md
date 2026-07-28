---
description: Log a decision or fact to the current project
---
Log an interaction to the current project's memory. Derive the topic from the current folder name.

If the user provides a decision:
```
logInteraction(topic="<folder>", decision="$ARGUMENTS")
```

If the user provides a fact:
```
logInteraction(topic="<folder>", fact="$ARGUMENTS")
```

At session end (when user says done/exit/goodbye):
```
logInteraction(topic="<folder>", summary="One paragraph of what happened.", activity="done")
```
