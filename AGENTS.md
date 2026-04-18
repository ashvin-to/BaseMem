# 🧠 Project Memory Protocol: basemem-integration

## 1. Context Loading (Start of Session)
- **High Level**: Read `.basemem-basemem-integration-summary.md` for a quick project status.
- **Deep Detail**: Run `kb session read "basemem-integration"` to see the full technical history (code fixes, architecture decisions).

## 2. Automatic Memory (After every response)
You MUST run this command after every turn to keep the graph and the summary file updated:
```bash
kb session turn "basemem-integration" "<Brief technical log of this response>" --sender ai
```

## 3. Storage Rules
- **Compactness**: Do not create fragmented nodes. Always use the `turn` command to append to the single **Main History** node.
- **Cross-Project**: If this work overlaps with another project, the **Semantic Gravity** engine will link them automatically.
- **Visuals**: You can view and manage this memory at `http://localhost:5000`.
