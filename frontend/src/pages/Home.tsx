import { useNavigate } from 'react-router-dom';
import { Database, Folder, ChevronRight, Brain, GitBranch, Network, Shield, Terminal } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Planet } from '../lib/types';

const features = [
  { icon: Brain, title: 'Persistent Memory', desc: 'AI agents remember decisions, facts, and context across sessions — no more repeating yourself.' },
  { icon: GitBranch, title: 'Project Context', desc: 'Each project gets its own "planet" with goal, state, next steps, and a timeline of notes.' },
  { icon: Network, title: 'Knowledge Graph', desc: 'Notes and code symbols are linked into a graph. Agents navigate relationships, not flat text.' },
  { icon: Shield, title: 'Agent-Agnostic', desc: 'Works with Claude Code, Cline, Codex, Cursor, Gemini, Devin, Kiro, and any MCP-compatible agent.' },
  { icon: Terminal, title: 'MCP Server', desc: 'Agents query their memory through the Model Context Protocol — structured, typed, always available.' },
];

export default function Home() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['planets'],
    queryFn: () => api.planets.list(),
  });

  const planets = data?.planets || [];

  return (
    <div className="overflow-y-auto h-full">
      <div className="max-w-3xl mx-auto px-8 pt-16 pb-8">
        <div className="flex items-center gap-4 mb-6">
          <Database className="w-10 h-10 text-amber-500" />
          <div>
            <h1 className="text-4xl font-bold text-foreground tracking-tight">BaseMem</h1>
            <p className="text-sm text-muted-foreground mt-0.5">v0.1 &mdash; Persistent Memory for AI Agents</p>
          </div>
        </div>

        <p className="text-lg text-foreground/80 leading-relaxed mb-10 max-w-2xl">
          BaseMem gives AI coding agents long-term memory. Every decision, fact, issue, and
          session summary is stored in a structured graph &mdash; accessible via MCP,
          CLI, or this web UI.
        </p>

        <div className="mb-12">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">How it Works</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {features.map((f) => (
              <div key={f.title} className="border border-border p-4 bg-card">
                <div className="flex items-start gap-3">
                  <f.icon className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <h3 className="font-medium text-sm text-foreground mb-1">{f.title}</h3>
                    <p className="text-xs text-muted-foreground leading-relaxed">{f.desc}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="border-t border-border">
        <div className="max-w-3xl mx-auto px-8 py-8">
          <h2 className="text-lg font-semibold text-foreground mb-4 flex items-center gap-2">
            <Folder className="w-5 h-5 text-amber-400" />
            Projects
          </h2>

          {isLoading && (
            <div className="flex items-center gap-3 text-muted-foreground py-8">
              <div className="w-5 h-5 border border-amber-500/50 animate-spin" />
              Loading projects...
            </div>
          )}

          <div className="space-y-1">
            {planets.map((planet: Planet) => (
              <button
                key={planet.topic}
                onClick={() => navigate(`/project/${encodeURIComponent(planet.topic)}`)}
                className="w-full text-left flex items-center justify-between px-4 py-3 hover:bg-accent/30 border border-transparent hover:border-border transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                  <div className="flex flex-col min-w-0">
                    <span className="font-medium text-sm text-foreground truncate">
                      {planet.display_topic || planet.topic}
                    </span>
                    {(planet.goal || planet.current_state) && (
                      <span className="text-xs text-muted-foreground truncate">
                        {planet.goal || planet.current_state}
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0 ml-4" />
              </button>
            ))}
          </div>

          {!isLoading && planets.length === 0 && (
            <div className="border border-dashed border-border p-8 text-center">
              <Database className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <h3 className="font-semibold text-foreground mb-2">No projects yet</h3>
              <p className="text-sm text-muted-foreground mb-4 max-w-md mx-auto">
                Projects are created automatically when AI agents start logging memory.
                To get started, install BaseMem and connect it to your AI coding tool.
              </p>
              <div className="text-xs text-left bg-card border border-border p-4 max-w-md mx-auto space-y-2">
                <p className="font-medium text-foreground mb-2">Quick start:</p>
                <code className="block text-muted-foreground">npm install -g basemem</code>
                <code className="block text-muted-foreground">basemem install &lt;agent&gt;</code>
                <code className="block text-muted-foreground">basemem mcp</code>
                <p className="text-muted-foreground mt-2">
                  Then ask your AI agent a question &mdash; it will create a project
                  and start recording memory automatically.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
