"""Main CLI interface using Click"""

import click
import asyncio
import json
from pathlib import Path
import logging
import os

from storage.db import StorageManager
from retrieval.engine import RetrievalEngine
from graph.engine import GraphEngine
from orchestrator.context import ContextOrchestrator
from processing.pipeline import ProcessingPipeline
from visualization.terminal import TerminalGraphVisualizer
from modelsimport NodeType, EdgeType

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@click.group()
@click.option('--db', help='Database file path')
@click.pass_context
def cli(ctx, db):
    """BaseMem: AI Knowledge Base System"""
    ctx.ensure_object(dict)
    ctx.obj['db'] = db
    ctx.obj['storage'] = StorageManager(db)


@cli.command()
@click.argument('text', required=False)
@click.option('--file', '-f', help='Path to a file to ingest')
@click.option('--source', default='cli', help='Source of the text')
@click.pass_context
def add(ctx, text, file, source):
    """Add text or file to knowledge base"""
    if not text and not file:
        click.echo("Error: Either TEXT argument or --file option must be provided.")
        return

    storage = ctx.obj['storage']
    graph_engine = GraphEngine(storage)
    pipeline = ProcessingPipeline(storage)

    if file:
        file_path = Path(file)
        if not file_path.exists():
            click.echo(f"Error: File {file} not found.")
            return
        with open(file_path, 'r') as f:
            content = f.read()
        source = source if source != 'cli' else file_path.name
    else:
        content = text

    async def process():
        nodes = await pipeline.ingest_text(content, source=source)
        
        # Auto-link new nodes
        total_edges = 0
        for node in nodes:
            edges = graph_engine.auto_link_nodes(node.id, threshold=0.2)
            total_edges += len(edges)
        
        click.echo(f"✓ Added {len(nodes)} nodes from {source}")
        for node in nodes:
            click.echo(f"  - {node.id[:8]}: {node.title}")
        
        if total_edges > 0:
            click.echo(f"✓ Auto-linked {total_edges} relationships")

    asyncio.run(process())


@cli.command()
@click.argument('query')
@click.option('--top-k', default=10, help='Number of results')
@click.pass_context
def search(ctx, query, top_k):
    """Search knowledge base"""
    storage = ctx.obj['storage']
    retrieval = RetrievalEngine(storage)

    results = retrieval.retrieve(query, top_k=top_k)

    if not results:
        click.echo("No results found")
        return

    click.echo(f"\n📚 Found {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        click.echo(f"{i}. [{result.source.upper()}] {result.node.title}")
        click.echo(f"   Score: {result.score:.3f} | Type: {result.node.node_type.value}")
        click.echo(f"   {result.node.content[:80]}...")
        click.echo()


@cli.command()
@click.argument('query')
@click.option('--token-budget', default=2000, help='Token budget for context')
@click.pass_context
def ask(ctx, query, token_budget):
    """Ask a question (RAG pipeline)"""
    storage = ctx.obj['storage']
    orchestrator = ContextOrchestrator(storage, token_budget=token_budget)

    context = orchestrator.orchestrate(query)

    click.echo(f"\n🔍 Query: {query}\n")
    click.echo("📖 Context:")
    click.echo(context.to_prompt_format())
    click.echo(f"\n📊 Stats: {len(context.source_nodes)} nodes, {context.token_count} tokens")


@cli.command()
@click.argument('node-id')
@click.option('--depth', default=1, help='Depth of neighbors to retrieve')
@click.pass_context
def graph(ctx, node_id, depth):
    """Explore graph around a node"""
    storage = ctx.obj['storage']
    graph_engine = GraphEngine(storage)

    node = storage.get_node(node_id)
    if not node:
        click.echo(f"Node not found: {node_id}")
        return

    click.echo(f"\n🔗 Graph for: {node.title}\n")
    click.echo(f"Node Type: {node.node_type.value}")
    click.echo(f"Weight: {node.weight} | Decay: {node.decay_score}\n")

    neighbors_dict = graph_engine.get_neighbors(node_id, depth=depth)

    if not neighbors_dict:
        click.echo("No neighbors found")
        return

    click.echo(f"Neighbors (depth={depth}):\n")
    for neighbor_id, neighbor in neighbors_dict.items():
        click.echo(f"  - {neighbor.title[:50]}")
        click.echo(f"    Type: {neighbor.node_type.value}")
        click.echo()


@cli.command()
@click.argument('concept')
@click.pass_context
def explain(ctx, concept):
    """Explain a concept using knowledge base"""
    storage = ctx.obj['storage']
    orchestrator = ContextOrchestrator(storage)

    context = orchestrator.orchestrate(concept)

    click.echo(f"\n📚 Explaining: {concept}\n")
    click.echo(context.to_prompt_format())


@cli.command()
@click.pass_context
def stats(ctx):
    """Show knowledge base statistics"""
    storage = ctx.obj['storage']

    nodes = storage.get_all_nodes()
    edges = storage.get_edges()

    click.echo("\n📊 Knowledge Base Statistics\n")
    click.echo(f"Total Nodes: {len(nodes)}")

    # Count by type
    type_counts = {}
    for node in nodes:
        node_type = node.node_type.value
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    click.echo("\nNodes by Type:")
    for node_type, count in sorted(type_counts.items()):
        click.echo(f"  {node_type}: {count}")

    click.echo(f"\nTotal Edges: {len(edges)}")

    # Count by edge type
    if edges:
        edge_type_counts = {}
        for edge in edges:
            edge_type = edge.edge_type.value
            edge_type_counts[edge_type] = edge_type_counts.get(edge_type, 0) + 1

        click.echo("\nEdges by Type:")
        for edge_type, count in sorted(edge_type_counts.items()):
            click.echo(f"  {edge_type}: {count}")

    # Average node weight
    avg_weight = sum(n.weight for n in nodes) / len(nodes) if nodes else 0
    click.echo(f"\nAverage Node Weight: {avg_weight:.3f}")


@cli.command()
@click.pass_context
def clear(ctx):
    """Clear the knowledge base"""
    if click.confirm("Are you sure you want to clear the knowledge base?"):
        storage = ctx.obj['storage']
        for node in storage.get_all_nodes():
            storage.delete_node(node.id)
        click.echo("✓ Knowledge base cleared")


@cli.command()
@click.pass_context
def show(ctx):
    """Show graph visualization (terminal)"""
    storage = ctx.obj['storage']
    graph_engine = GraphEngine(storage)
    viz = TerminalGraphVisualizer(storage, graph_engine)
    
    click.echo(viz.visualize_graph_summary())


@cli.command()
@click.argument('node-id')
@click.option('--depth', default=2, help='Depth of neighbors')
@click.pass_context
def view(ctx, node_id, depth):
    """View a node and its neighborhood"""
    storage = ctx.obj['storage']
    graph_engine = GraphEngine(storage)
    viz = TerminalGraphVisualizer(storage, graph_engine)
    
    click.echo(viz.visualize_node(node_id, depth=depth))


@cli.command()
@click.argument('from-id')
@click.argument('to-id')
@click.pass_context
def path(ctx, from_id, to_id):
    """Find shortest path between two nodes"""
    storage = ctx.obj['storage']
    graph_engine = GraphEngine(storage)
    viz = TerminalGraphVisualizer(storage, graph_engine)
    
    click.echo(viz.visualize_path(from_id, to_id))


@cli.command()
@click.option('--port', default=5000, help='Port to run server on')
@click.pass_context
def serve(ctx, port):
    """Start web server for graph visualization"""
    try:
        from serverimport app
        click.echo(f"🌐 Starting BaseMem server on http://localhost:{port}")
        click.echo(f"📊 Open http://localhost:{port}/../../graph_visualization.html")
        click.echo("Press Ctrl+C to stop")
        app.run(host="0.0.0.0", port=port, debug=False)
    except ImportError:
        click.echo("Error: Flask not installed. Install with: pip install flask")


@cli.command()
@click.argument('topic')
@click.pass_context
def review(ctx, topic):
    """Review the current session summary and recent history"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    session_node = manager.get_or_create_session(topic)
    history = manager.get_session_history(topic)
    
    click.echo(f"\n📋 Session Review: {topic}\n")
    click.echo("--- CURRENT SUMMARY ---")
    click.echo(session_node.content)
    
    click.echo("\n--- RECENT HISTORY ---")
    
    # Check if we have a "Main History" node
    main_history = next((n for n in history if n.metadata.get("is_main_history")), None)
    
    if main_history:
        # Parse the entries from the single large node
        # Entries are separated by "--- [TIMESTAMP] SENDER ---"
        entries = main_history.content.split("--- [")
        # The first part is usually the "Full conversation history..." header, skip it
        actual_entries = entries[1:] 
        
        for entry in actual_entries[-5:]: # Show last 5
            # Restore the separator for display
            click.echo(f"--- [{entry.strip()}")
            click.echo("")
    else:
        # Fallback for old multi-node history
        for chat in history[-5:]:
            sender = chat.metadata.get("sender", "unknown").upper()
            click.echo(f"[{sender}] {chat.content[:100]}...")


@cli.group()
def mcp():
    """Model Context Protocol (MCP) server commands"""
    pass


@mcp.command()
@click.option('--db', help='Database file path (overrides global db)')
@click.pass_context
def start(ctx, db):
    """Start the BaseMem MCP server"""
    db_path = db or ctx.obj['db']
    os.environ["BASEMEM_DB_PATH"] = str(Path(db_path).absolute())
    
    from ..mcp.server import mcp as mcp_server
    click.echo(f"🚀 Starting BaseMem MCP server (DB: {db_path})")
    mcp_server.run()


@cli.group()
def session():
    """Manage conversation sessions and summaries"""
    pass


@session.command()
@click.argument('topic')
@click.option('--file', help='Markdown file to export to')
@click.pass_context
def export(ctx, topic, file):
    """Export session summary to a markdown file"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    session_node = manager.get_or_create_session(topic)
    
    output_file = file or f".basemem-{topic}-summary.md"
    with open(output_file, "w") as f:
        f.write(f"# Session Summary: {topic}\n\n")
        f.write(session_node.content)
        f.write(f"\n\n---\n*Last Updated: {session_node.last_accessed.isoformat()}*")
    
    click.echo(f"✓ Exported session summary for '{topic}' to {output_file}")


@session.command(name='import')
@click.argument('topic')
@click.option('--file', help='Markdown file to import from')
@click.pass_context
def import_summary(ctx, topic, file):
    """Import session summary from a markdown file"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    input_file = file or f".basemem-{topic}-summary.md"
    if not Path(input_file).exists():
        click.echo(f"Error: File {input_file} not found")
        return
        
    with open(input_file, "r") as f:
        content = f.read()
    
    # Simple parsing to remove header if present
    if content.startswith("# Session Summary:"):
        lines = content.split("\n")
        # Find the first non-empty line after the header
        idx = 1
        while idx < len(lines) and (not lines[idx].strip() or lines[idx].startswith("# Session Summary:")):
            idx += 1
        
        # Remove footer if present
        end_idx = len(lines)
        for i, line in enumerate(lines):
            if line.strip() == "---" and i > idx:
                end_idx = i
                break
        
        summary_content = "\n".join(lines[idx:end_idx]).strip()
    else:
        summary_content = content.strip()

    manager.update_summary(topic, summary_content)
    click.echo(f"✓ Imported session summary for '{topic}' from {input_file}")


@session.command()
@click.argument('topic')
@click.option('--model', default='facebook/bart-large-cnn', help='HuggingFace model name (e.g., t5-small, facebook/bart-large-cnn)')
@click.pass_context
def summarize(ctx, topic, model):
    """Generate a local summary of the session history"""
    from storage.sessions import SessionManager
    from ..processing.summarizer import LocalSummarizer
    
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    history = manager.get_session_history(topic)
    if not history:
        click.echo(f"No history found for topic '{topic}' to summarize.")
        return
        
    click.echo(f"⏳ Generating local summary for '{topic}' using {model}...")
    summarizer = LocalSummarizer(model_name=model)
    summary_text = summarizer.summarize_chat_history(history)
    
    if summary_text:
        manager.update_summary(topic, summary_text)
        click.echo("\n✨ Local Summary Generated:")
        click.echo(summary_text)
        click.echo(f"\n✓ Session summary for '{topic}' updated in database.")
    else:
        click.echo(f"Error: Local summarization failed with model {model}.")


@session.command()
@click.argument('topic')
@click.argument('summary_text')
@click.pass_context
def update(ctx, topic, summary_text):
    """Update session summary directly (useful for AI agents)"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    manager.update_summary(topic, summary_text)
    click.echo(f"✓ Session summary for '{topic}' updated directly.")


@session.command()
@click.argument('topic')
@click.argument('message')
@click.option('--summary', help='Direct summary text (skips local summarization)')
@click.option('--sender', default='ai', help='Sender of the message')
@click.option('--model', default='t5-small', help='Model for local summarization fallback')
@click.pass_context
def turn(ctx, topic, message, summary, sender, model):
    """Log message, summarize history, and export (Complete Turn)"""
    from storage.sessions import SessionManager
    from ..processing.summarizer import LocalSummarizer
    
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    # 1. Log the chat
    manager.log_chat(topic, message, sender=sender)
    
    # 2. Get/Generate Summary
    if summary:
        summary_text = summary
    else:
        # Fallback to local model if no summary provided
        history = manager.get_session_history(topic)
        summarizer = LocalSummarizer(model_name=model)
        summary_text = summarizer.summarize_chat_history(history)
    
    if summary_text:
        manager.update_summary(topic, summary_text)
        
        # 3. Export
        output_file = f".basemem-{topic}-summary.md"
        with open(output_file, "w") as f:
            f.write(f"# Session Summary: {topic}\n\n")
            f.write(summary_text)
            f.write(f"\n\n---\n*Last Updated: {manager.get_or_create_session(topic).last_accessed.isoformat()}*")
            
        click.echo(f"✓ Session '{topic}' updated and exported to {output_file}")
    else:
        click.echo("Error: Summarization failed.")


@session.command()
@click.argument('topic')
@click.argument('message')
@click.option('--sender', default='ai', help='Sender of the message')
@click.pass_context
def log(ctx, topic, message, sender):
    """Log a raw chat message to the session"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    chat_node = manager.log_chat(topic, message, sender=sender)
    click.echo(f"✓ Logged {sender} message to session '{topic}' (Node: {chat_node.id[:8]})")


@session.command()
@click.argument('topic')
@click.option('--file', '-f', required=True, help='Path to transcript JSON/Text file')
@click.pass_context
def ingest(ctx, topic, file):
    """Save a full transcript as a single deterministic node (updates existing)"""
    from storage.sessions import SessionManager
    storage = ctx.obj['storage']
    manager = SessionManager(storage)
    
    file_path = Path(file)
    if not file_path.exists():
        click.echo(f"Error: File {file} not found.")
        return
        
    with open(file_path, 'r') as f:
        content = f.read()
        
    node = manager.ingest_transcript(topic, content)
    click.echo(f"✓ Full transcript for '{topic}' saved as node: {node.id}")
    click.echo(f"✓ Re-running this command for '{topic}' will update this exact node instead of duplicating.")


@session.command()
@click.argument('topic')
@click.pass_context
def read(ctx, topic):
    """Read the full transcript node for a topic"""
    storage = ctx.obj['storage']
    node_id = f"full-transcript-{topic.lower().replace(' ', '-')}"
    node = storage.get_node(node_id)
    if node:
        click.echo(f"\n📖 Full Transcript for '{topic}':\n")
        click.echo(node.content)
    else:
        # Fallback to main history node
        history_node_id = f"main-history-{topic.lower().replace(' ', '-')}"
        node = storage.get_node(history_node_id)
        if node:
            click.echo(f"\n📖 Main History for '{topic}':\n")
            click.echo(node.content)
        else:
            click.echo(f"No full transcript or main history node found for topic '{topic}'.")


@session.command()
@click.argument('topic')
@click.option('--path', default='.', help='Folder to bootstrap')
@click.pass_context
def bootstrap(ctx, topic, path):
    """Bootstrap a new project with AGENTS.md and a fresh database"""
    storage = ctx.obj['storage']
    from storage.sessions import SessionManager
    manager = SessionManager(storage)
    
    # 1. Initialize session in DB
    manager.get_or_create_session(topic)
    
    target_dir = Path(path).absolute()
    agents_file = target_dir / "AGENTS.md"
    
    # 2. Create AGENTS.md with the specific topic for THIS folder
    content = f"""# 🧠 Project Memory Protocol: {topic}

## 1. Context Loading (Start of Session)
- **High Level**: Read `.basemem-{topic}-summary.md`
- **Deep Detail**: Run `kb session read "{topic}"`

## 2. Automatic Memory (After every response)
You MUST run this command after every turn to keep the graph updated:
```bash
kb session turn "{topic}" "<Brief technical log of this response>" --sender ai
```

## 3. Storage
- All memory is saved to the local `basemem.db` in this folder.
- Do not create fragmented nodes; always use the `turn` command to append to the Main History.
"""
    with open(agents_file, "w") as f:
        f.write(content)
        
    click.echo(f"🚀 Project '{topic}' bootstrapped in {target_dir}")
    click.echo(f"✓ Created project-specific AGENTS.md")
    click.echo(f"✓ Future AIs will now automatically use the '{topic}' memory.")


if __name__ == '__main__':
    cli()
