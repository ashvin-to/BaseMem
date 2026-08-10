import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  Panel,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react';
import { Loader2, Search, X, Maximize2 } from 'lucide-react';
import { useSelection } from '../../context/SelectionContext';
import { DotNode, colorFor, KIND_COLORS } from '../graph/DotNode';
import type { GraphData, GraphNode, GraphEdge } from '../../lib/types';
import '@xyflow/react/dist/style.css';

type NodeData = {
  label: string;
  kind: string;
  color: string;
  planet?: string;
  note?: unknown;
};

const EDGE_TYPE_STYLE: Record<string, string> = {
  contains: '#7871d6',
  planet_link: '#f97316',
  related: '#6b7280',
  references: '#10b981',
};

const toGraphNode = (n: GraphNode): Node => {
  const isPlanet = n.type === 'planet' || n.id.startsWith('planet-');
  const note = (n.data?.note ?? {}) as Record<string, unknown>;
  const dataKind = (n.data?.kind as string) || '';
  const noteKind = note && Object.keys(note).length ? ((note.kind as string) || (isPlanet ? 'planet' : 'note')) : '';
  const typeKind = n.type || (isPlanet ? 'planet' : 'note');
  const resolvedKind = isPlanet ? 'planet' : (noteKind || dataKind || typeKind || 'note');
  const color = colorFor(n.data?.color as string || n.color || KIND_COLORS[resolvedKind] || KIND_COLORS[dataKind] || '#757575');
  const label = n.title || (n.data?.label as string) || (note.title as string) || n.id;
  const pos = n.position && (n.position.x !== 0 || n.position.y !== 0)
    ? { x: n.position.x, y: n.position.y }
    : { x: 0, y: 0 };
  return {
    id: n.id,
    type: 'dot',
    position: pos,
    data: {
      label,
      kind: resolvedKind,
      color,
      planet: n.planet || (note.topic as string) || n.group,
      note: n.data?.note,
    },
    style: { backgroundColor: 'transparent', border: 'none', padding: 0 },
  };
};

const toGraphEdge = (e: GraphEdge): Edge => ({
  id: e.id || `${e.source}:${e.target}`,
  source: e.source,
  target: e.target,
  type: 'smoothstep',
  animated: false,
  label: '',
  style: {
    stroke: EDGE_TYPE_STYLE[e.type || ''] || '#6b7280',
    strokeWidth: 1,
    strokeOpacity: 0.3,
  },
  markerEnd: { type: 'arrowclosed', color: EDGE_TYPE_STYLE[e.type || ''] || '#6b7280', width: 14, height: 14 },
});

export default function KnowledgeGraph({ projectId }: { projectId?: string }) {
  const { setSelection } = useSelection();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [rfInstance, setRfInstance] = useState<any>(null);
  const [fitToggled, setFitToggled] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [hovered, setHovered] = useState<{ data: NodeData; x: number; y: number } | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const fullNodesRef = useRef<Node[]>([]);
  const fullEdgesRef = useRef<Edge[]>([]);

  const { data: graphData, isLoading, error } = useQuery<GraphData>({
    queryKey: ['graph', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/graph/${encodeURIComponent(projectId || '')}`);
      if (!res.ok) throw new Error('Failed to fetch graph data');
      return res.json() as Promise<GraphData>;
    },
    enabled: !!projectId,
  });

  const applyDisplay = useCallback(() => {
    const full = fullNodesRef.current;
    const fullEdgeSet = fullEdgesRef.current;
    let toShow: Node[];
    let toShowEdges: Edge[];
    if (!searchQuery.trim()) {
      toShow = full;
      toShowEdges = fullEdgeSet;
    } else {
      const q = searchQuery.toLowerCase();
      const matchedIds = new Set(
        full
          .filter((n) => {
            const d = n.data as NodeData | undefined;
            return (
              (n.id ?? '').toLowerCase().includes(q) ||
              (d?.label ?? '').toLowerCase().includes(q) ||
              (d?.kind ?? '').toLowerCase().includes(q) ||
              (d?.planet ?? '').toLowerCase().includes(q)
            );
          })
          .map((n) => n.id)
      );
      toShow = full.filter((n) => matchedIds.has(n.id));
      toShowEdges = fullEdgeSet.filter((e) => matchedIds.has(e.source) && matchedIds.has(e.target));
    }
    const stamp = (list: Node[]) =>
      list.map((n) => ({ ...n, data: { ...(n.data as NodeData), showLabel: n.id === hoveredNodeId } }));
    setNodes(stamp(toShow));
    setEdges(toShowEdges);
  }, [searchQuery, hoveredNodeId, setNodes, setEdges]);

  useEffect(() => {
    if (!graphData) {
      setNodes([]);
      setEdges([]);
      fullNodesRef.current = [];
      fullEdgesRef.current = [];
      return;
    }
    fullNodesRef.current = (graphData.nodes || []).map((n, i) => {
      const node = toGraphNode(n);
      if (node.position.x === 0 && node.position.y === 0) {
        // Seeded pseudo-random for organic but deterministic layout
        const seed = (s: number) => {
          let x = Math.sin(s * 127.1 + 311.7) * 43758.5453;
          return x - Math.floor(x);
        };
        const r1 = seed(i * 2);
        const r2 = seed(i * 2 + 1);
        const angle = r1 * 2 * Math.PI;
        const radius = 150 + r2 * 450;
        node.position = { x: Math.round(500 + radius * Math.cos(angle)), y: Math.round(400 + radius * Math.sin(angle)) };
      }
      return node;
    });
    fullEdgesRef.current = (graphData.edges || []).map(toGraphEdge);
    applyDisplay();
  }, [graphData, applyDisplay]);

  useEffect(() => {
    applyDisplay();
  }, [applyDisplay, hoveredNodeId]);

  useEffect(() => {
    if (graphData && rfInstance && typeof rfInstance.fitViewport === 'function') {
      try {
        rfInstance.fitViewport({ padding: 40 });
      } catch (_) {
        /* fit not supported by this XYFlow version */
      }
    }
  }, [graphData, rfInstance]);

  const onConnect = useCallback(
    (params: Edge | Connection) => {
      setEdges((eds) => addEdge(params, eds as Edge[]));
      void fetch('/api/graph/edge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fromId: params.source, toId: params.target, edgeType: 'related' }),
      }).catch((e) => console.error('Failed to persist edge', e));
    },
    [setEdges]
  );

  const onNodeClick = useCallback(
    async (_: React.MouseEvent, node: Node) => {
      const data = node.data as NodeData;
      if (data.kind === 'planet') {
        const slug = node.id.replace(/^planet-/, '');
        setSelection({ type: 'planet', id: node.id, data: { topic: slug, goal: data.label, display_topic: data.label } });
        return;
      }
      // Prefer the note content embedded in the graph node (no extra request).
      const embedded = data.note as Record<string, unknown> | undefined;
      if (embedded && typeof embedded.content === 'string' && embedded.content) {
        setSelection({
          type: 'note',
          id: node.id,
          data: {
            title: (embedded.title as string) || data.label,
            kind: data.kind || (embedded.kind as string) || 'note',
            content: embedded.content,
            topic: (embedded.topic as string) || data.planet || projectId,
            created_at: embedded.created_at as string | null,
            agent_id: embedded.agent_id as string | null,
          },
        });
        return;
      }
      // Fallback: fetch the note detail from the API.
      const noteId = node.id.replace(/^note-/, '');
      if (!noteId) return;
      try {
        const res = await fetch(`/api/notes/${noteId}`);
        const payload = res.ok ? await res.json().catch(() => ({})) : {};
        const note = (payload.note || {}) as Record<string, unknown>;
        setSelection({
          type: 'note',
          id: node.id,
          data: {
            title: (note.title as string) || data.label,
            kind: data.kind || (note.kind as string) || 'note',
            content: typeof note.content === 'string' ? note.content : '',
            topic: (note.topic as string) || data.planet || projectId,
            created_at: note.created_at as string | null,
            agent_id: note.agent_id as string | null,
          },
        });
      } catch {
        setSelection({ type: 'note', id: node.id, data: { title: data.label, kind: data.kind, content: '', topic: data.planet } });
      }
    },
    [setSelection, projectId]
  );

  const fitView = () => {
    if (rfInstance && typeof rfInstance.fitViewport === 'function') {
      try {
        rfInstance.fitViewport({ padding: 32 });
      } catch (_) {
        /* no-op on unsupported versions */
      }
    }
    setFitToggled(true);
    setTimeout(() => setFitToggled(false), 600);
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        Loading graph...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <span className="text-red-400/70 mr-2">⚠</span>
        Could not load graph: {(error as Error)?.message}
      </div>
    );
  }

  const legendKinds = Array.from(
    new Set(fullNodesRef.current.map((n) => (n.data as NodeData)?.kind).filter(Boolean))
  ).sort();

  return (
    <div className="relative w-full h-full" data-bm-graph="true">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={{ dot: DotNode }}
        onInit={setRfInstance}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={(_, node: Node) => {
          setHoveredNodeId(node.id);
          if (node.data) setHovered({ data: node.data as NodeData, x: 0, y: 0 });
        }}
        onNodeMouseMove={(event, node: Node) => {
          setHoveredNodeId(node.id);
          if (node.data) setHovered({ data: node.data as NodeData, x: event.clientX, y: event.clientY });
        }}
        onNodeMouseLeave={() => {
          setHoveredNodeId(null);
          setHovered(null);
        }}
        nodeOrigin={[0, 0]}
        fitView
        colorMode="dark"
        defaultEdgeOptions={{ animated: false, style: { strokeOpacity: 0.6 } }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background color="#3f3f46" gap={16} />
        <Controls position="bottom-left" />
        <MiniMap nodeStrokeWidth={3} zoomable pannable nodeColor={(n: any) => colorFor(n?.data?.color)} />

        <Panel position="top-left" className="bm-panel">
          <div className="flex items-center gap-2 mb-2">
            <button
              onClick={fitView}
              className="p-2 rounded bg-card border border-border hover:border-amber-500/60 text-muted-foreground hover:text-foreground transition-colors"
              title="Fit to screen"
            >
              <Maximize2 className={`w-4 h-4 ${fitToggled ? 'text-amber-400' : ''}`} />
            </button>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1.5 bg-background/80 border border-border rounded text-xs text-muted-foreground">
            <Search className="w-3 h-3" />
            <input
              type="text"
              placeholder="Filter nodes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-transparent border-none outline-none text-foreground placeholder:text-muted-foreground/50 w-36"
            />
            {searchQuery && (
              <X className="w-3 h-3 cursor-pointer text-muted-foreground hover:text-foreground" onClick={() => setSearchQuery('')} />
            )}
          </div>
        </Panel>

        <Panel position="top-right" className="bm-panel">
          <div className="flex flex-wrap gap-2 p-2 bg-card/80 border border-border rounded text-xs text-muted-foreground max-w-48">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500 border border-amber-500" />
              Planet
            </div>
            {legendKinds.filter((k) => k !== 'planet').map((k) => (
              <div key={k} className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-full border"
                  style={{ backgroundColor: `${colorFor(EDGE_TYPE_STYLE[k] || '#757575')}40` }}
                />
                {k}
              </div>
            ))}
          </div>
        </Panel>
      </ReactFlow>

      {hovered && (
        <div
          className="fixed pointer-events-none z-[1000] px-2.5 py-1.5 bg-popover border border-border rounded shadow-lg text-xs text-foreground whitespace-nowrap"
          style={{
            left: hovered.x + 14,
            top: hovered.y + 14,
            boxShadow: '0 10px 25px rgba(0,0,0,0.4)',
          }}
        >
          <div className="font-medium">{hovered.data.label}</div>
          <div className="text-muted-foreground capitalize">{hovered.data.kind}</div>
          {hovered.data.planet && <div className="text-muted-foreground">planet: {hovered.data.planet}</div>}
        </div>
      )}
    </div>
  );
}
