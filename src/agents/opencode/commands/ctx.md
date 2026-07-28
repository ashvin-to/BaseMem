---
description: Fetch memory context for a project topic
---
Fetch the memory context for this project. If a topic is provided as $1, use it. Otherwise derive from the current folder name.

```
getContext(topic="$1", query="$ARGUMENTS")
```

If the context is empty or the topic doesn't exist, suggest creating a planet:
```
update_planet(topic="<topic>", goal="Describe the project goal")
```
