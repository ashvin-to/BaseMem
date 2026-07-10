import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Brain, Code2, GitMerge } from 'lucide-react';
import { cn } from '../lib/utils';
import PlanetMemory from '../components/project/PlanetMemory';
import CodeIntelligence from '../components/project/CodeIntelligence';
import KnowledgeGraph from '../components/project/KnowledgeGraph';

type Tab = 'memory' | 'code' | 'graph';

export default function ProjectView() {
  const { id } = useParams();
  const [activeTab, setActiveTab] = useState<Tab>('memory');

  return (
    <div className="flex flex-col h-full w-full relative">
      {/* Tab Navigation */}
      <div className="flex items-center gap-1 border-b border-border p-2 bg-card/30">
        <button
          onClick={() => setActiveTab('memory')}
          className={cn(
            "flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
            activeTab === 'memory' ? "bg-accent text-accent-foreground" : "hover:bg-accent/50 text-muted-foreground"
          )}
        >
          <Brain className="w-4 h-4" />
          Planet Memory
        </button>
        <button
          onClick={() => setActiveTab('code')}
          className={cn(
            "flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
            activeTab === 'code' ? "bg-accent text-accent-foreground" : "hover:bg-accent/50 text-muted-foreground"
          )}
        >
          <Code2 className="w-4 h-4" />
          Code Intelligence
        </button>
        <button
          onClick={() => setActiveTab('graph')}
          className={cn(
            "flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
            activeTab === 'graph' ? "bg-accent text-accent-foreground" : "hover:bg-accent/50 text-muted-foreground"
          )}
        >
          <GitMerge className="w-4 h-4" />
          Knowledge Graph
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'memory' && <PlanetMemory projectId={id} />}
        {activeTab === 'code' && <CodeIntelligence projectId={id} />}
        {activeTab === 'graph' && <KnowledgeGraph projectId={id} />}
      </div>
    </div>
  );
}
