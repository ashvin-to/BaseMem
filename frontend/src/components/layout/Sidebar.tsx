import { NavLink } from 'react-router-dom';
import { Database, Folder } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import type { Planet } from '../../lib/types';

export default function Sidebar() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['planets'],
    queryFn: () => api.planets.list(),
  });

  const planets = data?.planets || [];

  return (
    <div className="flex flex-col h-full text-muted-foreground">
      <div className="p-6 border-b border-border">
        <a href="/" className="font-bold text-xl flex items-center gap-3 text-foreground hover:opacity-80 transition-opacity">
          <Database className="w-6 h-6 text-amber-500" />
          BaseMem
        </a>
      </div>
      
      <div className="p-4 flex-1 overflow-y-auto">
        <div className="text-xs font-semibold text-muted-foreground mb-4 px-3">
          Projects
        </div>
        
        {isLoading && <div className="px-3 text-sm text-muted-foreground animate-pulse">Loading planets...</div>}
        {error && <div className="px-3 text-sm text-red-400">Failed to load API</div>}

        <div className="space-y-1">
          {planets.map((planet: Planet) => (
            <NavLink
              key={planet.topic}
              to={`/project/${encodeURIComponent(planet.topic)}`}
              className={({ isActive }) => cn(
                "flex flex-col px-4 py-3 border",
                isActive 
                  ? "bg-accent/50 border-border text-foreground" 
                  : "border-transparent text-muted-foreground hover:bg-accent/30 hover:text-foreground"
              )}
            >
              <div className="flex items-center gap-3">
                <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                <span className="truncate text-sm">{planet.display_topic || planet.topic}</span>
              </div>
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}
