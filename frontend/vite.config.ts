import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import os from 'os'
import fs from 'fs'

const CODE_DB_FILE = '.basemem.code.db'

function loadPathStore(): Record<string, string> {
  const file = path.join(os.homedir(), '.basemem', 'project_paths.json')
  try {
    if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch { /* ignore corrupt store */ }
  return {}
}

function savePathStore(map: Record<string, string>): void {
  const file = path.join(os.homedir(), '.basemem', 'project_paths.json')
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(map, null, 2))
}

const _SKIP_DIRS = new Set(['node_modules', '.git', 'dist', 'build', '.next', '.basemem', '.cache'])

function _validDirs(dir: string, depth: number): string[] {
  if (depth < 0) return []
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return []
  const out: string[] = [dir]
  try {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory() && !_SKIP_DIRS.has(e.name)) {
        out.push(..._validDirs(path.join(dir, e.name), depth - 1))
      }
    }
  } catch { /* ignore */ }
  return out
}

// Resolve a planet topic to its local source root: honours an explicit stored
// path, then auto-scans common roots for a project dir (name match) that
// contains a .basemem.code.db. Auto-detected paths are remembered in the store.
function resolveProjectPath(topic: string): string | null {
  if (!topic) return null
  const store = loadPathStore()
  if (store[topic] && fs.existsSync(store[topic])) return store[topic]
  const roots = [os.homedir(), '/mnt/Storage', process.cwd(), '/workspace']
  for (const root of roots) {
    for (const full of _validDirs(root, 2)) {
      if (fs.existsSync(path.join(full, CODE_DB_FILE)) && path.basename(full).toLowerCase() === topic.toLowerCase()) {
        savePathStore({ ...store, [topic]: full })
        return full
      }
    }
  }
  return null
}

// Custom Vite plugin to serve BaseMem SQLite data without needing Python backend
function basememApiPlugin() {
  return {
    name: 'basemem-api',
    configureServer(server: any) {
      server.middlewares.use(async (req: any, res: any, next: any) => {
        if (!req.url.startsWith('/api/')) return next()
        let Database: any
        try {
          const mod = await import('better-sqlite3')
          Database = mod.default
        } catch {
          res.statusCode = 503
          res.setHeader('Content-Type', 'application/json')
          return res.end(JSON.stringify({ error: 'SQLite not available in this environment' }))
        }
        
        try {
          const dbPath = path.join(os.homedir(), '.basemem', 'basemem.db')
          const db = new Database(dbPath, { readonly: true })
          
          if (req.url === '/api/planets' && req.method === 'GET') {
            const rows = db.prepare('SELECT * FROM planets ORDER BY updated_at DESC').all()
            const planets = rows.map((r: any) => ({
              ...r,
              next_steps: r.next_steps ? JSON.parse(r.next_steps) : [],
              files: r.files ? JSON.parse(r.files) : []
            }))
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ planets }))
          }

          if (req.url.startsWith('/api/planets/') && req.method === 'GET') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0])
            const planet = db.prepare('SELECT * FROM planets WHERE topic = ?').get(topic) as any
            if (!planet) {
              res.statusCode = 404
              return res.end(JSON.stringify({ error: 'Not found' }))
            }
            const notes = db.prepare("SELECT * FROM notes WHERE topic = ? AND kind != 'turn' ORDER BY created_at DESC LIMIT 50").all(topic)
            planet.next_steps = planet.next_steps ? JSON.parse(planet.next_steps) : []
            planet.files = planet.files ? JSON.parse(planet.files) : []
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ ...planet, notes }))
          }

          if (req.url === '/api/graph/edge' && req.method === 'POST') {
            let body = '';
            req.on('data', (chunk: any) => { body += chunk.toString() });
            req.on('end', () => {
              try {
                const { fromId, toId, edgeType } = JSON.parse(body);
                const writeDb = new Database(dbPath);
                const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
                writeDb.prepare(`
                  INSERT OR REPLACE INTO edges (from_id, to_id, edge_type, weight, created_at)
                  VALUES (?, ?, ?, 1.0, ?)
                `).run(fromId, toId, edgeType || 'related', now);
                writeDb.close();
                res.setHeader('Content-Type', 'application/json');
                return res.end(JSON.stringify({ success: true }));
              } catch (e: any) {
                res.statusCode = 400;
                return res.end(JSON.stringify({ error: e.message }));
              }
            });
            return;
          }

          if (req.url.startsWith('/api/graph/') && req.method === 'GET') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0])
            const planet = db.prepare('SELECT * FROM planets WHERE topic = ?').get(topic) as any
            const notes = db.prepare("SELECT * FROM notes WHERE topic = ? AND kind != 'turn' ORDER BY created_at DESC LIMIT 50").all(topic)
            
            // Also pull code symbols if the code DB exists
            const projectPath = resolveProjectPath(topic);
            let codeSymbols: any[] = [];
            let codeEdges: any[] = [];
            if (projectPath) {
              const codeDbPath = path.join(projectPath, '.basemem.code.db');
              if (fs.existsSync(codeDbPath)) {
                try {
                  const codeDb = new Database(codeDbPath, { readonly: true });
                  codeSymbols = codeDb.prepare(`
                    SELECT id, symbol_name, symbol_type, kind, file_path, start_line
                    FROM code_symbols WHERE project_id = ? ORDER BY id
                  `).all(topic) as any[];
                  codeEdges = codeDb.prepare(`
                    SELECT from_symbol_id, to_symbol_id, from_name, to_name, edge_type
                    FROM code_edges WHERE project_id = ? LIMIT 800
                  `).all(topic) as any[];
                  codeDb.close();
                } catch (_) {}
              }
            }

            const nodes: any[] = []
            const edges: any[] = []
            
            const seed = (s: number) => {
              let x = Math.sin(s * 127.1 + 311.7) * 43758.5453;
              return x - Math.floor(x);
            };

            if (planet) {
              nodes.push({
                id: `planet-${topic}`,
                position: { x: 500, y: 400 },
                data: { label: planet.display_topic || topic, kind: 'planet', color: '#f97316' },
                type: 'dot',
              })
            }
            
            // Add note nodes as dots
            notes.forEach((note: any, index: number) => {
              const r1 = seed(index * 3);
              const r2 = seed(index * 3 + 1);
              const angle = r1 * 2 * Math.PI;
              const radius = 200 + r2 * 350;
              const x = 500 + radius * Math.cos(angle);
              const y = 400 + radius * Math.sin(angle);

              const noteColor: Record<string, string> = {
                decision: '#eab308', fact: '#22c55e', summary: '#a855f7',
                concept: '#7c3aed', turn: '#06b6d4',
              };
              const kind = note.kind || 'note';
              nodes.push({
                id: `note-${note.id}`,
                position: { x, y },
                data: { label: note.title || note.content.substring(0, 40), kind, color: noteColor[kind] || '#94a3b8', note },
                type: 'dot',
              })
              edges.push({
                id: `edge-${topic}-${note.id}`,
                source: `planet-${topic}`,
                target: `note-${note.id}`,
              })
            })

            // Add code symbol nodes as dots
            const KIND_DOT_COLOR: Record<string, string> = {
              function: '#60a5fa', method: '#60a5fa', class: '#a855f7',
              module: '#22c55e', variable: '#eab308', import: '#f97316',
              constant: '#06b6d4', interface: '#7c3aed', type_alias: '#7c3aed',
              arrow: '#94a3b8', symbol: '#94a3b8',
            };
            const noteCount = notes.length;
            codeSymbols.forEach((s, i) => {
              const r1 = seed((noteCount + i) * 3);
              const r2 = seed((noteCount + i) * 3 + 1);
              const angle = r1 * 2 * Math.PI;
              const radius = 150 + r2 * 500;
              const x = 500 + radius * Math.cos(angle);
              const y = 400 + radius * Math.sin(angle);
              const kind = s.kind || s.symbol_type || 'symbol';
              nodes.push({
                id: `sym-${s.id}`,
                position: { x, y },
                data: { label: s.symbol_name || `Symbol ${s.id}`, kind, color: KIND_DOT_COLOR[kind] || '#94a3b8' },
                type: 'dot',
              });
            });

            // Add code edges (calls, imports between symbols)
            codeEdges.forEach((e, i) => {
              edges.push({
                id: `code-edge-${i}`,
                source: `sym-${e.from_symbol_id}`,
                target: `sym-${e.to_symbol_id}`,
                type: e.edge_type,
              });
            });
            
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ nodes, edges }))
          }

          if (req.url.startsWith('/api/paths/') && req.method === 'GET') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0])
            const p = resolveProjectPath(topic)
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ path: p || '', resolved: !!p }))
          }

          if (req.url.startsWith('/api/paths/') && req.method === 'POST') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0])
            
            let body = ''
            req.on('data', (chunk: any) => { body += chunk.toString() })
            req.on('end', () => {
              try {
                const data = JSON.parse(body)
                const pathsFile = path.join(os.homedir(), '.basemem', 'project_paths.json')
                let paths: Record<string, string> = {}
                const fs = require('fs')
                if (fs.existsSync(pathsFile)) {
                  paths = JSON.parse(fs.readFileSync(pathsFile, 'utf-8'))
                }
                paths[topic] = data.path
                fs.writeFileSync(pathsFile, JSON.stringify(paths, null, 2))
                
                res.setHeader('Content-Type', 'application/json')
                res.end(JSON.stringify({ success: true, path: data.path }))
              } catch (e: any) {
                res.statusCode = 400
                res.end(JSON.stringify({ error: e.message }))
              }
            })
            return
          }

          if (req.url.startsWith('/api/code/')) {
            const parts = req.url.split('?')[0].split('/');
            const action = parts[3];
            const topic = decodeURIComponent(parts[4] || '');
            const projectPath = resolveProjectPath(topic);

            if (!projectPath) {
              res.statusCode = 404;
              return res.end(JSON.stringify({ error: 'Project path not configured or detected' }));
            }
            
            const codeDbPath = path.join(projectPath, '.basemem.code.db');
            if (!fs.existsSync(codeDbPath)) {
              res.statusCode = 404;
              return res.end(JSON.stringify({ error: 'Code DB not found. Run mem code init.' }));
            }
            
            const codeDb = new Database(codeDbPath, { readonly: true });
            
            if (action === 'stats') {
              const projectInfo = codeDb.prepare('SELECT file_count, symbol_count FROM code_projects LIMIT 1').get() as any;
              const edgesCount = codeDb.prepare('SELECT count(*) as count FROM code_edges').get() as any;
              
              let files = projectInfo?.file_count || 0;
              let symbols = projectInfo?.symbol_count || 0;
              
              if (!projectInfo) {
                const filesCount = codeDb.prepare('SELECT count(DISTINCT file_path) as count FROM code_symbols').get() as any;
                const symbolsCount = codeDb.prepare('SELECT count(*) as count FROM code_symbols').get() as any;
                files = filesCount.count;
                symbols = symbolsCount.count;
              }
              
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({
                files,
                symbols,
                references: edgesCount.count,
                dbPath: codeDbPath
              }));
            }
            
            if (action === 'files') {
              const getAllFiles = (dirPath: string, arrayOfFiles: string[] = []) => {
                try {
                  const files = fs.readdirSync(dirPath);
                  files.forEach((file: string) => {
                    const fullPath = path.join(dirPath, file);
                    if (fs.statSync(fullPath).isDirectory()) {
                      if (!['node_modules', '.git', 'build', 'dist', '.next', '.basemem'].includes(file)) {
                        arrayOfFiles = getAllFiles(fullPath, arrayOfFiles);
                      }
                     } else {
                      // Get path relative to project root, normalise to forward slashes for UI
                      if (file === CODE_DB_FILE || file.startsWith('.basemem')) return;
                      const relativePath = fullPath.substring(projectPath.length).replace(/^[\\\/]+/, '').replace(/\\/g, '/');
                      arrayOfFiles.push(relativePath);
                    }
                  });
                } catch (e) {
                  console.error('Error reading directory', e);
                }
                return arrayOfFiles;
              };
              
              const allFiles = getAllFiles(projectPath);
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({ files: allFiles }));
            }
            
            if (action === 'search') {
              const urlParams = new URLSearchParams(req.url.split('?')[1] || '');
              const q = urlParams.get('q') || '';
              if (!q) {
                res.setHeader('Content-Type', 'application/json');
                return res.end(JSON.stringify({ results: [] }));
              }
              const rows = codeDb.prepare(`
                SELECT id, symbol_name, symbol_type, file_path, start_line, kind
                FROM code_symbols 
                WHERE symbol_name LIKE ? OR file_path LIKE ?
                LIMIT 50
              `).all(`%${q}%`, `%${q}%`);
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({ results: rows }));
            }
            
            if (action === 'content') {
              const urlParams = new URLSearchParams(req.url.split('?')[1] || '');
              const file = urlParams.get('file') || '';
              if (!file) {
                res.statusCode = 400;
                return res.end(JSON.stringify({ error: 'file param required' }));
              }
              const fullPath = path.join(projectPath, file);
              if (!fs.existsSync(fullPath)) {
                res.statusCode = 404;
                return res.end(JSON.stringify({ error: 'File not found' }));
              }
              const ext = path.extname(file).slice(1);
              const content = fs.readFileSync(fullPath, 'utf-8');
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({ content, language: ext }));
            }

            if (action === 'graph') {
              // Pull ALL symbols as nodes (even edgeless ones), up to 800 edges for display
              const allSymbols = codeDb.prepare(`
                SELECT id, symbol_name, symbol_type, kind, file_path, start_line
                FROM code_symbols
                WHERE project_id = ?
                ORDER BY id
              `).all(topic || 'basemem') as any[];
              
              const edges = codeDb.prepare(`
                SELECT from_symbol_id, to_symbol_id, from_name, to_name, edge_type
                FROM code_edges
                WHERE project_id = ?
                LIMIT 800
              `).all(topic || 'basemem') as any[];
              
              // Build node map from all symbols (not just those in edges)
              const nodesMap = new Map<string, any>();
              allSymbols.forEach((s) => {
                const key = s.id.toString();
                if (!nodesMap.has(key)) {
                  nodesMap.set(key, {
                    id: key,
                    symbolName: s.symbol_name,
                    kind: s.kind || s.symbol_type || 'symbol',
                    filePath: s.file_path,
                    label: s.symbol_name || `Symbol ${s.id}`,
                  });
                }
              });
              // Merge edge-referenced targets if not already in map
              edges.forEach(e => {
                const fk = e.from_symbol_id?.toString();
                const tk = e.to_symbol_id?.toString();
                if (fk && !nodesMap.has(fk)) {
                  nodesMap.set(fk, { id: fk, symbolName: e.from_name, kind: 'symbol', label: e.from_name || `Symbol ${fk}` });
                }
                if (tk && !nodesMap.has(tk)) {
                  nodesMap.set(tk, { id: tk, symbolName: e.to_name, kind: 'symbol', label: e.to_name || `Symbol ${tk}` });
                }
              });
              
              const nodesArr = Array.from(nodesMap.values());
              const KIND_DOT_COLOR: Record<string, string> = {
                function: '#60a5fa', method: '#60a5fa', class: '#a855f7',
                module: '#22c55e', variable: '#eab308', import: '#f97316',
                constant: '#06b6d4', interface: '#7c3aed', type_alias: '#7c3aed',
                arrow: '#94a3b8', symbol: '#94a3b8',
              };
              
              // Seeded pseudo-random for organic but deterministic layout
              const seed = (s: number) => {
                let x = Math.sin(s * 127.1 + 311.7) * 43758.5453;
                return x - Math.floor(x);
              };
              
              const reactNodes = nodesArr.map((n, i) => {
                // Organic scatter: seeded random per node, spread across area
                const r1 = seed(i * 2);
                const r2 = seed(i * 2 + 1);
                const angle = r1 * 2 * Math.PI;
                const radius = 150 + r2 * 500; // 150-650px from center
                const x = 600 + radius * Math.cos(angle);
                const y = 400 + radius * Math.sin(angle);
                
                const dotColor = KIND_DOT_COLOR[n.kind] || KIND_DOT_COLOR.symbol;
                return {
                  id: `sym-${n.id}`,
                  data: { label: n.label, kind: n.kind, color: dotColor },
                  position: { x, y },
                  type: 'dot',
                };
              });
              
              const reactEdges = edges.map((e, i) => ({
                id: `edge-${i}`,
                source: `sym-${e.from_symbol_id}`,
                target: `sym-${e.to_symbol_id}`,
                animated: e.edge_type === 'calls',
                label: e.edge_type,
              }));
              
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({ nodes: reactNodes, edges: reactEdges }));
            }
          }

          // --- Write operations ---
          if (req.url.match(/^\/api\/notes\/\d+/) && req.method === 'GET') {
            const noteId = parseInt(decodeURIComponent(req.url.split('/')[3].split('?')[0]), 10);
            const note = db.prepare('SELECT * FROM notes WHERE id = ?').get(noteId) as any;
            if (!note) {
              res.statusCode = 404;
              return res.end(JSON.stringify({ error: 'Note not found' }));
            }
            res.setHeader('Content-Type', 'application/json');
            return res.end(JSON.stringify({ note, neighbors: [] }));
          }

          if (req.url === '/api/notes' && req.method === 'POST') {
            let body = '';
            req.on('data', (chunk: any) => { body += chunk.toString() });
            req.on('end', () => {
              try {
                const data = JSON.parse(body);
                const writeDb = new Database(dbPath);
                const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
                const result = writeDb.prepare(`
                  INSERT INTO notes (topic, kind, title, content, created_at, updated_at)
                  VALUES (?, ?, ?, ?, ?, ?)
                `).run(data.topic, data.kind || 'note', data.title || '', data.content || '', now, now);
                writeDb.close();
                res.setHeader('Content-Type', 'application/json');
                return res.end(JSON.stringify({ success: true, id: result.lastInsertRowid }));
              } catch (e: any) {
                res.statusCode = 400;
                return res.end(JSON.stringify({ error: e.message }));
              }
            });
            return;
          }

          if (req.url.startsWith('/api/planets/') && req.method === 'PUT') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0]);
            let body = '';
            req.on('data', (chunk: any) => { body += chunk.toString() });
            req.on('end', () => {
              try {
                const data = JSON.parse(body);
                const writeDb = new Database(dbPath);
                const existing = writeDb.prepare('SELECT * FROM planets WHERE topic = ?').get(topic) as any;
                const now = new Date().toISOString().slice(0, 19).replace('T', ' ');

                if (existing) {
                  const updates: string[] = [];
                  const params: any[] = [];
                  for (const key of ['display_topic', 'goal', 'current_state', 'status']) {
                    if (data[key] !== undefined) {
                      updates.push(`${key} = ?`);
                      params.push(data[key]);
                    }
                  }
                  if (data.next_steps !== undefined) {
                    updates.push('next_steps = ?');
                    params.push(JSON.stringify(data.next_steps));
                  }
                  updates.push('updated_at = ?');
                  params.push(now);
                  params.push(topic);
                  writeDb.prepare(`UPDATE planets SET ${updates.join(', ')} WHERE topic = ?`).run(...params);
                } else {
                  writeDb.prepare(`
                    INSERT INTO planets (topic, display_topic, goal, current_state, status, next_steps, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                  `).run(
                    topic, data.display_topic || topic, data.goal || '', data.current_state || '',
                    data.status || 'active', JSON.stringify(data.next_steps || []), now, now
                  );
                }
                writeDb.close();
                res.setHeader('Content-Type', 'application/json');
                return res.end(JSON.stringify({ success: true }));
              } catch (e: any) {
                res.statusCode = 400;
                return res.end(JSON.stringify({ error: e.message }));
              }
            });
            return;
          }

          if (req.url.startsWith('/api/search/global') && req.method === 'GET') {
            const urlParams = new URLSearchParams(req.url.split('?')[1] || '')
            const q = urlParams.get('q') || ''
            if (!q) {
              res.setHeader('Content-Type', 'application/json')
              return res.end(JSON.stringify({ planets: [], notes: [] }))
            }
            const query = `%${q}%`
            const planets = db.prepare(`
              SELECT topic, display_topic, goal, current_state 
              FROM planets 
              WHERE topic LIKE ? OR display_topic LIKE ? OR goal LIKE ? OR current_state LIKE ? 
              LIMIT 10
            `).all(query, query, query, query)
            
            const notes = db.prepare(`
              SELECT id, topic, kind, title, content, created_at
              FROM notes 
              WHERE (title LIKE ? OR content LIKE ?) AND kind != 'turn'
              ORDER BY created_at DESC 
              LIMIT 20
            `).all(query, query)
            
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ planets, notes }))
          }

          next()
        } catch (error: any) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: error.message }))
        }
      })
    }
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss(), basememApiPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
