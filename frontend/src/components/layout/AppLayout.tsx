import { Outlet, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import DetailsPanel from './DetailsPanel';
import { useEffect, useState, useRef } from 'react';
import { Search, X, Folder, ChevronRight, FileText, Database, Loader2 } from 'lucide-react';
import { api } from '../../lib/api';
import type { Planet, Note } from '../../lib/types';

export default function AppLayout() {
  const [shortcutPrefix, setShortcutPrefix] = useState('Ctrl');
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [allProjects, setAllProjects] = useState<Planet[]>([]);
  const [matchedPlanets, setMatchedPlanets] = useState<Planet[]>([]);
  const [matchedNotes, setMatchedNotes] = useState<Note[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      setShortcutPrefix(isMac ? '⌘' : 'Ctrl');

      const handleKeyDown = (e: KeyboardEvent) => {
        if ((isMac ? e.metaKey : e.ctrlKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          setIsSearchOpen(true);
        }
        if (e.key === 'Escape') {
          setIsSearchOpen(false);
        }
      };

      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, []);

  useEffect(() => {
    if (isSearchOpen) {
      if (searchInputRef.current) searchInputRef.current.focus();
      api.planets.list()
        .then(data => {
          setAllProjects(data.planets);
          setMatchedPlanets(data.planets);
        })
        .catch(console.error);
    } else {
      setSearchQuery('');
      setMatchedNotes([]);
    }
  }, [isSearchOpen]);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setMatchedPlanets(allProjects);
      setMatchedNotes([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const timeout = setTimeout(() => {
      api.search.global(searchQuery)
        .then(data => {
          setMatchedPlanets(data.planets);
          setMatchedNotes(data.notes);
        })
        .catch(console.error)
        .finally(() => setIsSearching(false));
    }, 300);

    return () => clearTimeout(timeout);
  }, [searchQuery, allProjects]);

  return (
    <div className="flex h-screen w-full bg-background text-foreground">
      <div className="w-64 border-r border-border flex-shrink-0">
        <Sidebar />
      </div>

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="h-14 border-b border-border flex items-center px-6">
          <div className="flex-1"></div>
          <button 
            onClick={() => setIsSearchOpen(true)}
            className="text-sm text-muted-foreground flex items-center gap-3 px-4 py-2 border border-border hover:bg-accent/50 transition-colors"
          >
            <Search className="w-4 h-4" />
            <span>Search everywhere...</span>
            <kbd className="border border-border px-2 py-0.5 text-xs font-mono text-muted-foreground ml-4">
              {shortcutPrefix} K
            </kbd>
          </button>
        </div>
        
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </div>

      <div className="w-80 border-l border-border flex-shrink-0">
        <DetailsPanel />
      </div>

      {isSearchOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-background/80">
          <div className="absolute inset-0" onClick={() => setIsSearchOpen(false)}></div>
          
          <div className="relative w-full max-w-xl bg-card border border-border overflow-hidden">
            <div className="flex items-center px-4 border-b border-border">
              {isSearching ? (
                <Loader2 className="w-5 h-5 shrink-0 text-amber-500 animate-spin" />
              ) : (
                <Search className="w-5 h-5 shrink-0 text-amber-400" />
              )}
              <input 
                ref={searchInputRef}
                type="text" 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search projects and memory..." 
                className="flex-1 bg-transparent border-none text-foreground px-4 py-4 focus:outline-none placeholder:text-muted-foreground text-lg"
              />
              <button 
                onClick={() => setIsSearchOpen(false)}
                className="p-1 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="max-h-[60vh] overflow-y-auto p-2">
              {matchedPlanets.length === 0 && matchedNotes.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  {isSearching ? 'Searching...' : `No results for "${searchQuery}"`}
                </div>
              ) : (
                <div className="space-y-4">
                  {matchedPlanets.length > 0 && (
                    <div className="space-y-1">
                      <div className="px-3 py-2 text-xs font-semibold text-muted-foreground flex items-center gap-2">
                        <Database className="w-3 h-3" /> Planets
                      </div>
                      {matchedPlanets.map(p => (
                        <button
                          key={`planet-${p.topic}`}
                          onClick={() => {
                            setIsSearchOpen(false);
                            navigate(`/project/${encodeURIComponent(p.topic)}`);
                          }}
                          className="w-full text-left flex items-center justify-between px-3 py-3 hover:bg-accent/30 text-muted-foreground hover:text-foreground transition-colors"
                        >
                          <div className="flex flex-col gap-1 overflow-hidden">
                            <div className="flex items-center gap-3">
                              <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                              <span className="font-medium text-sm truncate">{p.display_topic || p.topic}</span>
                            </div>
                            {searchQuery && (p.goal || p.current_state) && (
                              <div className="text-xs text-muted-foreground pl-7 truncate">
                                {p.goal || p.current_state}
                              </div>
                            )}
                          </div>
                          <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
                        </button>
                      ))}
                    </div>
                  )}

                  {matchedNotes.length > 0 && (
                    <div className="space-y-1">
                      <div className="px-3 py-2 text-xs font-semibold text-muted-foreground flex items-center gap-2">
                        <FileText className="w-3 h-3" /> Notes
                      </div>
                      {matchedNotes.map(n => (
                        <button
                          key={`note-${n.id}`}
                          onClick={() => {
                            setIsSearchOpen(false);
                            navigate(`/project/${encodeURIComponent(n.topic)}`);
                          }}
                          className="w-full text-left flex items-start gap-3 px-3 py-3 hover:bg-accent/30 text-muted-foreground hover:text-foreground transition-colors"
                        >
                          <FileText className="w-4 h-4 mt-0.5 text-amber-400 shrink-0" />
                          <div className="flex flex-col overflow-hidden w-full">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-sm truncate capitalize">
                                {n.kind}: {n.title || n.content.substring(0, 30)}
                              </span>
                              <span className="text-xs text-muted-foreground shrink-0 truncate max-w-[80px]">
                                {n.topic}
                              </span>
                            </div>
                            <span className="text-xs text-muted-foreground truncate mt-1">{n.content}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
