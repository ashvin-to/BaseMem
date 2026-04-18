import json
import argparse
from pathlib import Path
from src.basemem.storage.db import StorageManager
from src.basemem.storage.sessions import SessionManager
from src.basemem.models import Node, NodeType, Edge, EdgeType

def main():
    parser = argparse.ArgumentParser(description="Import a Gemini CLI JSON history file into BaseMem")
    parser.add_argument("--topic", required=True, help="Topic name for the session")
    parser.add_argument("--file", required=True, help="Path to the JSON history file")
    args = parser.parse_args()

    topic = args.topic
    file_path = args.file
    history_node_id = f"main-history-{topic.lower().replace(' ', '-')}"

    if not Path(file_path).exists():
        print(f"Error: File {file_path} not found.")
        return

    with open(file_path, "r") as f:
        data = json.load(f)

    transcript = f"Full conversation history for topic: {topic}\n"

    # Extract messages from the JSON structure
    messages = data.get("messages", [])
    if not messages and isinstance(data, list):
        messages = data # Handle different JSON formats if necessary

    for msg in messages:
        sender = msg.get("type", "unknown").upper()
        if sender == "INFO":
            continue
        
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            content_str = "\n".join(text_parts)
        else:
            content_str = str(content)
            
        if not content_str.strip():
            continue
            
        timestamp = msg.get("timestamp", "unknown")
        transcript += f"\n\n--- [{timestamp}] {sender} ---\n{content_str}"

    storage = StorageManager("basemem.db")
    manager = SessionManager(storage)
    
    # Ensure the session summary node exists
    manager.get_or_create_session(topic)
    
    # Ingest using our new deterministic logic
    node = manager.ingest_transcript(topic, transcript)
    
    # Rename node ID to match our "Main History" convention if needed
    # (The ingest_transcript uses full-transcript-, but we want main-history- for 2-node consistency)
    storage.delete_node(node.id)
    node.id = history_node_id
    node.title = f"Main History: {topic}"
    node.metadata["is_main_history"] = True
    
    # Extract keywords
    new_words = [w.lower() for w in transcript.split() if len(w) > 4 and w.isalnum()]
    node.keywords = list(set(new_words))[:50]
    
    storage.add_node(node)
    
    # Ensure link to summary
    summary_node = manager.get_or_create_session(topic)
    edge = Edge(
        from_id=node.id,
        to_id=summary_node.id,
        edge_type=EdgeType.PART_OF,
        weight=1.0,
        confidence=1.0
    )
    storage.add_edge(edge)

    print(f"✓ Successfully imported '{topic}' into the 2-Node memory system.")
    print(f"✓ Created/Updated node: {node.id} ({len(transcript)} characters)")
    
    storage.close()

if __name__ == "__main__":
    main()
