import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, FileCode2, GitFork, Box, FolderTree, Loader2, Save, Database as DatabaseIcon, ChevronRight, ChevronDown, Folder as FolderIcon, FileText, X } from 'lucide-react';
import { ReactFlow, MiniMap, Controls, Background } from '@xyflow/react';
import { useSelection } from '../../context/SelectionContext';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import type { Planet, CodeSearchResult } from '../../lib/types';
import '@xyflow/react/dist/style.css';

type SubTab = 'overview' | 'explorer' | 'search' | 'callgraph';

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children: Record<string, FileNode>;
}

const LANG_MAP: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  rs: 'rust', py: 'python', go: 'go', java: 'java', rb: 'ruby',
  css: 'css', scss: 'scss', html: 'html', json: 'json', md: 'markdown',
  yaml: 'yaml', yml: 'yaml', toml: 'toml', sh: 'bash', bash: 'bash',
  c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp',
};

const buildTree = (files: string[]) => {
  const root: FileNode = { name: 'root', path: '', isDir: true, children: {} };
  files.forEach(file => {
    const parts = file.split('/').filter(Boolean);
    let current = root;
    parts.forEach((part, i) => {
      if (i === parts.length - 1) {
        current.children[part] = { name: part, path: file, isDir: false, children: {} };
      } else {
        if (!current.children[part]) {
          const folderPath = parts.slice(0, i + 1).join('/');
          current.children[part] = { name: part, path: folderPath, isDir: true, children: {} };
        }
        current = current.children[part];
      }
    });
  });
  return root;
};

const FileTreeNode = ({ node, projectId, onSelectFile }: { node: FileNode; projectId?: string; onSelectFile: (path: string) => void }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!node.isDir) {
    return (
      <div
        className="flex items-center gap-2 py-1 px-2 hover:bg-amber-500/10 cursor-pointer text-amber-200/80 hover:text-amber-300 rounded transition-colors ml-4"
        onClick={() => onSelectFile(node.path)}
      >
        <FileText className="w-3.5 h-3.5 opacity-60 shrink-0" />
        <span className="truncate text-[13px]">{node.name}</span>
      </div>
    );
  }

  if (node.name === 'root') {
    return (
      <div className="py-2">
        {Object.values(node.children).sort((a, b) => (a.isDir === b.isDir ? 0 : a.isDir ? -1 : 1)).map(child => (
          <FileTreeNode key={child.path} node={child} projectId={projectId} onSelectFile={onSelectFile} />
        ))}
      </div>
    );
  }

  return (
    <div className="ml-4">
      <div
        className="flex items-center gap-2 py-1 px-2 hover:bg-white/5 cursor-pointer text-white/70 hover:text-white rounded transition-colors"
        onClick={() => setIsOpen(!isOpen)}
      >
        {isOpen ? <ChevronDown className="w-3.5 h-3.5 shrink-0 opacity-50" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-50" />}
        <FolderIcon className="w-3.5 h-3.5 text-amber-400 shrink-0" />
        <span className="truncate font-medium text-[13px]">{node.name}</span>
      </div>
      {isOpen && (
        <div className="border-l border-white/10 ml-2 mt-0.5">
          {Object.values(node.children).sort((a, b) => (a.isDir === b.isDir ? 0 : a.isDir ? -1 : 1)).map(child => (
            <FileTreeNode key={child.path} node={child} projectId={projectId} onSelectFile={onSelectFile} />
          ))}
        </div>
      )}
    </div>
  );
};

export default function CodeIntelligence({ projectId }: { projectId?: string }) {
  const [subTab, setSubTab] = useState<SubTab>('overview');
  const [inputPath, setInputPath] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { setSelection } = useSelection();

  const { data: planet } = useQuery({
    queryKey: ['planet', projectId],
    queryFn: () => api.planets.get(projectId || ''),
    enabled: !!projectId,
  });

  const { data: projectPath, isLoading: isPathLoading } = useQuery({
    queryKey: ['projectPath', projectId],
    queryFn: () => api.paths.get(projectId || '').then(d => d.path),
    enabled: !!projectId,
  });

  const { data: codeStats, isLoading: isStatsLoading } = useQuery({
    queryKey: ['codeStats', projectId],
    queryFn: () => api.code.stats(projectId || ''),
    enabled: !!projectId && !!projectPath,
  });

  const { data: codeFiles } = useQuery({
    queryKey: ['codeFiles', projectId],
    queryFn: () => api.code.files(projectId || ''),
    enabled: !!projectId && !!projectPath,
  });

  const { data: searchResults, isLoading: isSearchLoading } = useQuery({
    queryKey: ['codeSearch', projectId, searchQuery],
    queryFn: () => api.code.search(projectId || '', searchQuery),
    enabled: !!projectId && !!projectPath && searchQuery.length > 0,
  });

  const { data: fileContent, isLoading: isFileLoading } = useQuery({
    queryKey: ['fileContent', projectId, selectedFile],
    queryFn: () => api.code.fileContent(projectId || '', selectedFile!),
    enabled: !!projectId && !!selectedFile,
  });

  const { data: graphData } = useQuery({
    queryKey: ['codeGraph', projectId],
    queryFn: () => api.code.graph(projectId || ''),
    enabled: !!projectId && !!projectPath && subTab === 'callgraph',
  });

  const pathMutation = useMutation({
    mutationFn: (path: string) => api.paths.set(projectId || '', path),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectPath', projectId] });
      queryClient.invalidateQueries({ queryKey: ['codeStats', projectId] });
      queryClient.invalidateQueries({ queryKey: ['codeFiles', projectId] });
    },
  });

  if (!planet && !isPathLoading) {
    return <div className="flex h-full items-center justify-center text-muted-foreground"><Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading code intelligence...</div>;
  }

  const displayFiles = codeFiles?.files?.length > 0 ? codeFiles.files : ((planet as Planet)?.files || []);

  return (
    <div className="flex flex-col h-full bg-background">
      <div className="flex items-center gap-4 px-4 py-2 border-b border-border text-sm">
        <button onClick={() => setSubTab('overview')} className={cn("pb-1 border-b-2 transition-colors", subTab === 'overview' ? "border-amber-500 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>Overview</button>
        <button onClick={() => setSubTab('explorer')} className={cn("pb-1 border-b-2 transition-colors", subTab === 'explorer' ? "border-amber-500 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>File Explorer</button>
        <button onClick={() => setSubTab('search')} className={cn("pb-1 border-b-2 transition-colors", subTab === 'search' ? "border-amber-500 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>Symbol Search</button>
        <button onClick={() => setSubTab('callgraph')} className={cn("pb-1 border-b-2 transition-colors", subTab === 'callgraph' ? "border-amber-500 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>Call Graph</button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {!projectPath && (
          <div className="max-w-3xl mx-auto mb-8 bg-card border border-border p-6 rounded-xl shadow-sm">
            <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
              <DatabaseIcon className="w-5 h-5 text-amber-400" />
              Connect Local Code Database
            </h3>
            <p className="text-sm text-muted-foreground mb-4">
              To enable deep code intelligence (symbols, references, and search), please provide the absolute path to this project on your system where <code className="bg-accent px-1 py-0.5 rounded text-xs text-foreground">.basemem.code.db</code> is located.
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="e.g. /mnt/Storage/OpenTune"
                value={inputPath}
                onChange={(e) => setInputPath(e.target.value)}
                className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-amber-500"
              />
              <button
                onClick={() => pathMutation.mutate(inputPath)}
                disabled={!inputPath || pathMutation.isPending}
                className="bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                {pathMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                Save Path
              </button>
            </div>
          </div>
        )}

        {subTab === 'overview' && (
          <div className="max-w-3xl mx-auto space-y-6">
            <h2 className="text-xl font-semibold">Code Index Overview: {(planet as Planet)?.display_topic || (planet as Planet)?.topic}</h2>
            {projectPath && (
              <div className="text-xs text-muted-foreground bg-accent/30 inline-block px-2 py-1 rounded font-mono">
                Connected: {projectPath}
              </div>
            )}
            <div className="grid grid-cols-3 gap-4">
              <div className="p-4 border border-border rounded-xl bg-card">
                <FileCode2 className="w-6 h-6 text-amber-400 mb-2" />
                <div className="text-2xl font-bold">
                  {isStatsLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : (codeStats?.files ?? displayFiles.length)}
                </div>
                <div className="text-sm text-muted-foreground">Indexed Files</div>
              </div>
              <div className={cn("p-4 border border-border rounded-xl bg-card", !codeStats && "opacity-50")}>
                <Box className="w-6 h-6 text-amber-400 mb-2" />
                <div className="text-2xl font-bold">
                  {isStatsLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : (codeStats?.symbols ?? '-')}
                </div>
                <div className="text-sm text-muted-foreground">Symbols</div>
              </div>
              <div className={cn("p-4 border border-border rounded-xl bg-card", !codeStats && "opacity-50")}>
                <GitFork className="w-6 h-6 text-amber-400 mb-2" />
                <div className="text-2xl font-bold">
                  {isStatsLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : (codeStats?.references ?? '-')}
                </div>
                <div className="text-sm text-muted-foreground">References</div>
              </div>
            </div>
          </div>
        )}

        {subTab === 'explorer' && (
          <div className="max-w-5xl mx-auto h-full flex flex-col">
            <div className="flex items-center gap-2 mb-4 text-muted-foreground shrink-0">
              <FolderTree className="w-5 h-5" />
              <span>Project Files</span>
            </div>
            <div className="flex gap-4 flex-1 min-h-0">
              <div className="w-72 shrink-0 p-2 border border-white/10 rounded-xl bg-[#0f0f11]/80 backdrop-blur-xl font-mono text-sm overflow-y-auto custom-scrollbar shadow-[0_0_20px_rgba(0,0,0,0.2)]">
                {displayFiles.length === 0 ? (
                  <div className="text-white/40 italic p-4 text-center">No files found.</div>
                ) : (
                  <FileTreeNode node={buildTree(displayFiles)} projectId={projectId} onSelectFile={setSelectedFile} />
                )}
              </div>
              <div className="flex-1 border border-white/10 rounded-xl bg-[#0f0f11]/80 backdrop-blur-xl overflow-hidden shadow-[0_0_20px_rgba(0,0,0,0.2)] flex flex-col">
                {selectedFile ? (
                  <>
                    <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 text-sm text-white/60 shrink-0">
                      <span className="font-mono truncate">{selectedFile}</span>
                      <button onClick={() => setSelectedFile(null)} className="p-1 hover:bg-white/5 rounded transition-colors">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-auto p-4 custom-scrollbar">
                      {isFileLoading ? (
                        <div className="flex items-center justify-center h-full text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...</div>
                      ) : fileContent ? (
                        <pre className="text-sm font-mono text-white/80 whitespace-pre-wrap"><code>{fileContent.content}</code></pre>
                      ) : (
                        <div className="text-muted-foreground text-center py-10">Could not load file.</div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                    Select a file from the tree to view its contents.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {subTab === 'search' && (
          <div className="max-w-3xl mx-auto">
            <div className="relative mb-6">
              <Search className="absolute left-3 top-2.5 w-5 h-5 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search functions, classes, interfaces..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-card border border-border rounded-lg pl-10 pr-4 py-2 text-foreground focus:outline-none focus:border-amber-500 transition-colors"
                disabled={!codeStats}
              />
            </div>
            {!codeStats ? (
              <div className="text-center text-muted-foreground py-10 border border-dashed border-border rounded-xl">
                Symbol search requires connection to the local project's .basemem.code.db
              </div>
            ) : (
              <div className="space-y-2 h-[60vh] overflow-y-auto">
                {isSearchLoading ? (
                  <div className="flex justify-center p-8 text-muted-foreground"><Loader2 className="w-6 h-6 animate-spin" /></div>
                ) : searchResults?.results?.length ? (
                  searchResults.results.map((result: CodeSearchResult, i: number) => (
                    <div
                      key={i}
                      className="p-3 bg-card border border-border rounded-lg hover:border-amber-500/50 cursor-pointer transition-colors"
                      onClick={() => setSelection({ type: 'code', id: `sym-${result.id}`, data: { kind: result.symbol_type, title: result.symbol_name, content: `Path: ${result.file_path}\nLine: ${result.start_line}\nType: ${result.symbol_type}` } })}
                    >
                      <div className="flex items-center gap-2">
                        <Box className="w-4 h-4 text-amber-400" />
                        <span className="font-semibold">{result.symbol_name}</span>
                        <span className="text-xs px-2 py-0.5 bg-accent rounded text-muted-foreground">{result.symbol_type}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1 font-mono truncate">{result.file_path}:{result.start_line}</div>
                    </div>
                  ))
                ) : searchQuery ? (
                  <div className="text-center text-muted-foreground py-8">No symbols found for "{searchQuery}"</div>
                ) : null}
              </div>
            )}
          </div>
        )}

        {subTab === 'callgraph' && (
          <div className="h-full flex flex-col">
            {!codeStats ? (
              <div className="flex-1 flex items-center justify-center text-muted-foreground border border-dashed border-border rounded-xl p-8 max-w-3xl mx-auto w-full">
                Interactive Call Graph requires .basemem.code.db connection.
              </div>
            ) : (
              <div className="flex-1 w-full bg-background rounded-xl border border-border overflow-hidden relative min-h-[60vh]">
                {!graphData ? (
                  <div className="absolute inset-0 flex items-center justify-center"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
                ) : (
                  <ReactFlow
                    nodes={graphData.nodes || []}
                    edges={graphData.edges || []}
                    fitView
                    colorMode="dark"
                  >
                    <Controls />
                    <MiniMap nodeStrokeWidth={3} zoomable pannable />
                    <Background color="#3f3f46" gap={16} />
                  </ReactFlow>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
