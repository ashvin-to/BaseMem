# Universal Agent Rules & Memory Protocol

## 🧠 Compact Memory Protocol
This project uses a 2-node hierarchical memory in BaseMem.

### 1. The Structure
- **Node A (Summary)**: Concise project status.
- **Node B (Main History)**: A single large node containing the entire chat history.

### 2. Mandatory Workflow
After EVERY response you give, you MUST run this command to update the memory:
```bash
kb session turn "archii" "<Brief log of this turn>" --sender ai
```

### 3. Start of Session
1. Read the .basemem-archii-summary.md file for context.
2. For deep technical details, read the Main History node:
   `kb session read "archii"`
