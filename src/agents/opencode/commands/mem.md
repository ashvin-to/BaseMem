---
description: Show memory status for the current project
---
Show the memory status for this project. Derive the topic from the current folder name.

```
read_planet(topic="<folder>")
```

If no planet exists, suggest creating one:
```
update_planet(topic="<folder>", goal="Describe the project goal")
```
