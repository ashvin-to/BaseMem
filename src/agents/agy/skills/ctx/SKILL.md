---
name: ctx
description: Fetch memory context for a project topic
---

Fetch the memory context for this project.

```
getContext(topic="<folder-name>", query="optional question")
```

If the topic doesn't exist, create a planet:
```
update_planet(topic="<folder-name>", goal="Describe the project goal")
```
