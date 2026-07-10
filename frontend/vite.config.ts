import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import os from 'os'

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
            
            const nodes: any[] = []
            const edges: any[] = []
            
            if (planet) {
              nodes.push({ id: `planet-${topic}`, position: { x: 400, y: 300 }, data: { label: `Project: ${planet.display_topic || topic}` }, type: 'input', className: 'bg-indigo-500/10 border-indigo-500/30 text-indigo-100 font-bold shadow-[0_0_20px_rgba(99,102,241,0.2)] rounded-full px-6 py-4' })
            }
            
            notes.forEach((note: any, index: number) => {
              // Fermat's spiral (Sunflower layout) for organic, non-overlapping nodes
              // Use a large scaling factor to account for the physical width of the HTML nodes
              const angle = index * 2.4; // ~137.5 degrees (Golden angle)
              const radius = 250 + 120 * Math.sqrt(index);
              
              const x = 400 + radius * Math.cos(angle)
              const y = 300 + radius * Math.sin(angle)

              // Determine color based on kind
              let borderClass = 'border-white/10'
              let bgClass = 'bg-[#0f0f11]/90'
              if (note.kind === 'decision') { borderClass = 'border-amber-500/30'; bgClass = 'bg-amber-500/10' }
              else if (note.kind === 'fact') { borderClass = 'border-emerald-500/30'; bgClass = 'bg-emerald-500/10' }
              else if (note.kind === 'summary') { borderClass = 'border-purple-500/30'; bgClass = 'bg-purple-500/10' }

              nodes.push({
                id: `note-${note.id}`,
                position: { x, y },
                className: `${bgClass} ${borderClass} text-white/80 rounded-xl px-4 py-3 backdrop-blur-md shadow-lg transition-all hover:shadow-[0_0_15px_rgba(255,255,255,0.1)]`,
                data: { 
                  label: `${note.kind}: ${note.title || note.content.substring(0, 30)}`,
                  note: note
                }
              })
              edges.push({
                id: `edge-${topic}-${note.id}`,
                source: `planet-${topic}`,
                target: `note-${note.id}`,
                animated: true
              })
            })
            
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ nodes, edges }))
          }

          if (req.url.startsWith('/api/paths/') && req.method === 'GET') {
            const topic = decodeURIComponent(req.url.split('/')[3].split('?')[0])
            const pathsFile = path.join(os.homedir(), '.basemem', 'project_paths.json')
            let paths: Record<string, string> = {}
            if (require('fs').existsSync(pathsFile)) {
              paths = JSON.parse(require('fs').readFileSync(pathsFile, 'utf-8'))
            }
            res.setHeader('Content-Type', 'application/json')
            return res.end(JSON.stringify({ path: paths[topic] || null }))
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
            const action = parts[3]; // stats, files, search, graph
            const topic = decodeURIComponent(parts[4] || '');
            
            const pathsFile = path.join(os.homedir(), '.basemem', 'project_paths.json');
            let paths: Record<string, string> = {};
            const fs = require('fs');
            if (fs.existsSync(pathsFile)) {
              paths = JSON.parse(fs.readFileSync(pathsFile, 'utf-8'));
            }
            const projectPath = paths[topic];
            
            if (!projectPath) {
              res.statusCode = 404;
              return res.end(JSON.stringify({ error: 'Project path not configured' }));
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
              const edges = codeDb.prepare(`
                SELECT from_symbol_id, to_symbol_id, from_name, to_name, edge_type
                FROM code_edges 
                LIMIT 100
              `).all() as any[];
              
              const nodesMap = new Map();
              edges.forEach(e => {
                if (!nodesMap.has(e.from_symbol_id)) {
                  nodesMap.set(e.from_symbol_id, { id: e.from_symbol_id.toString(), label: e.from_name });
                }
                if (!nodesMap.has(e.to_symbol_id)) {
                  nodesMap.set(e.to_symbol_id, { id: e.to_symbol_id.toString(), label: e.to_name });
                }
              });
              
              const totalNodes = nodesMap.size;
              const reactNodes = Array.from(nodesMap.values()).map((n, i) => {
                // Fermat's spiral (Sunflower layout) for organic, non-overlapping nodes
                const angle = i * 2.4; // ~137.5 degrees (Golden angle)
                const radius = 250 + 100 * Math.sqrt(i);
                
                const x = 500 + radius * Math.cos(angle);
                const y = 300 + radius * Math.sin(angle);

                return {
                  id: `sym-${n.id}`,
                  data: { label: n.label || `Symbol ${n.id}` },
                  position: { x, y },
                  className: 'bg-[#0f0f11]/90 border-indigo-500/20 text-white/80 rounded-lg px-4 py-2 backdrop-blur-md shadow-[0_0_15px_rgba(0,0,0,0.5)] transition-all hover:border-indigo-400/50 hover:shadow-[0_0_20px_rgba(99,102,241,0.2)]'
                };
              });
              
              const reactEdges = edges.map((e, i) => ({
                id: `edge-${i}`,
                source: `sym-${e.from_symbol_id}`,
                target: `sym-${e.to_symbol_id}`,
                animated: true,
                label: e.edge_type
              }));
              
              res.setHeader('Content-Type', 'application/json');
              return res.end(JSON.stringify({ nodes: reactNodes, edges: reactEdges }));
            }
          }

          // --- Write operations ---
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
  base: process.env.VERCEL ? '/' : '/BaseMem/',
  plugins: [react(), tailwindcss(), basememApiPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
