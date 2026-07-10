import { useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
} from '@xyflow/react';
import type { Connection, Edge, Node } from '@xyflow/react';
import { Loader2 } from 'lucide-react';
import { useSelection } from '../../context/SelectionContext';
import '@xyflow/react/dist/style.css';

export default function KnowledgeGraph({ projectId }: { projectId?: string }) {
  const { setSelection } = useSelection();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const { data: graphData, isLoading } = useQuery({
    queryKey: ['graph', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/graph/${encodeURIComponent(projectId || '')}`);
      if (!res.ok) throw new Error('Failed to fetch graph data');
      return res.json() as Promise<{ nodes: Node[], edges: Edge[] }>;
    },
    enabled: !!projectId
  });

  useEffect(() => {
    if (graphData) {
      setNodes(graphData.nodes);
      setEdges(graphData.edges);
    }
  }, [graphData, setNodes, setEdges]);

  const onConnect = useCallback(
    async (params: Edge | Connection) => {
      setEdges((eds) => addEdge(params, eds));
      try {
        await fetch('/api/graph/edge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fromId: params.source, toId: params.target, edgeType: 'related' }),
        });
      } catch (e) {
        console.error('Failed to persist edge', e);
      }
    },
    [setEdges],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.id.startsWith('note-') && node.data.note) {
        setSelection({ type: 'note', id: node.id, data: node.data.note });
      } else if (node.id.startsWith('planet-')) {
        setSelection({ type: 'planet', id: node.id, data: { topic: projectId, goal: node.data.label } });
      }
    },
    [setSelection, projectId]
  );

  if (isLoading) {
    return <div className="flex h-full items-center justify-center text-muted-foreground"><Loader2 className="w-6 h-6 animate-spin mr-2"/> Loading graph...</div>;
  }

  return (
    <div className="w-full h-full bg-background" style={{ height: 'calc(100vh - 100px)' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        fitView
        colorMode="dark"
      >
        <Controls />
        <MiniMap nodeStrokeWidth={3} zoomable pannable />
        <Background color="#3f3f46" gap={16} />
      </ReactFlow>
    </div>
  );
}
