// basemem — OpenCode v2 plugin. v2 requires `export default { id, setup }`; a named
// `export const X = async () => ({...})` is the v1 shape and fails to load.
// __BASEMEM_ROOT__ is replaced at install time. Re-run `node bin/lib/install.js repair opencode`.

import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { execFileSync, spawn } from 'node:child_process'

const INTEGRITY_WARNING =
  'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.'

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || '__BASEMEM_ROOT__'
const RULES_MODULE = path.join(BASEMEM_ROOT, 'bin', 'lib', 'rules.js')
const CAPTURE_PY = path.join(BASEMEM_ROOT, 'bin', 'lib', 'capture_native.py')

const STOP_PHRASES = [
  'goodbye',
  'exit',
  'done for today',
  'closing',
  'end session',
  "that's all",
  'thanks bye',
]
const STOP_NUDGE =
  'FINAL SESSION NOTICE — do not respond to this message. If you made decisions, created files, or changed direction this session and have not yet called logInteraction, call it once now with a one-paragraph summary. Then stop. Do not send any further messages or acknowledge this notice.'
const MEMORY_REMINDER =
  '[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).'

const configDir = path.join(os.homedir(), '.config', 'opencode')
const flagFile = path.join(configDir, '.basemem-active')
const agentsMd = path.join(configDir, 'AGENTS.md')

function loadRules() {
  try {
    const mod = require(RULES_MODULE)
    if (mod && mod.BASEMEM_RULES_CORE) return mod.BASEMEM_RULES_CORE
  } catch (_) {}
  return ''
}

function projectNameFrom(dir) {
  let current = dir
  for (let i = 0; i <= 3; i++) {
    try {
      const pkgPath = path.join(current, 'package.json')
      if (fs.existsSync(pkgPath)) {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'))
        if (pkg.name) return pkg.name
      }
      const pyprojectPath = path.join(current, 'pyproject.toml')
      if (fs.existsSync(pyprojectPath)) {
        const content = fs.readFileSync(pyprojectPath, 'utf-8')
        const match = content.match(/^name\s*=\s*"([^"]+)"/m)
        if (match) return match[1]
      }
    } catch (_) {}
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  return path.basename(dir)
}

function resolveProjectName(locations) {
  for (const dir of locations) {
    if (!dir) continue
    try {
      if (fs.statSync(dir).isDirectory()) return projectNameFrom(dir)
    } catch (_) {}
  }
  const cwd = process.env.PWD && fs.existsSync(process.env.PWD) ? process.env.PWD : process.cwd()
  return path.basename(cwd)
}

function runMem(args, timeout) {
  try {
    const bin = process.env.BASEMEM_BIN_DIR ? path.join(process.env.BASEMEM_BIN_DIR, 'mem') : 'mem'
    return execFileSync(bin, args, { timeout, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] })
      .toString()
      .trim()
  } catch (_) {
    return ''
  }
}

function fetchMemContext(projectName) {
  if (!projectName) return ''
  return runMem(['agent-context', '--topic', projectName], 3000)
}

function fetchPromptContext(promptText, topic) {
  if (!promptText || promptText.trim().length < 8) return ''
  return runMem(
    ['prompt-context', '--topic', topic || resolveProjectName([]), '--query', promptText.slice(0, 2000)],
    4000,
  ).slice(0, 2000)
}

function integrityCheckedRules(rules) {
  if (!rules) return INTEGRITY_WARNING
  try {
    if (fs.readFileSync(agentsMd, 'utf-8').includes('basemem-managed-start')) return rules
  } catch (_) {}
  return INTEGRITY_WARNING + '\n\n' + rules
}

function markActive() {
  try {
    fs.mkdirSync(configDir, { recursive: true })
    fs.writeFileSync(flagFile, 'active', 'utf-8')
  } catch (_) {}
}

function markStopFired() {
  try {
    fs.mkdirSync(configDir, { recursive: true })
    const existing = fs.existsSync(flagFile) ? fs.readFileSync(flagFile, 'utf-8') : ''
    fs.writeFileSync(flagFile, existing + '\nstop-fired@' + Date.now(), 'utf-8')
  } catch (_) {}
}

function captureToolUse(tool, params) {
  const python = process.env.BASEMEM_PYTHON || process.env.MCP_PYTHON || 'python3'
  let child
  try {
    child = spawn(python, [CAPTURE_PY], { stdio: ['pipe', 'ignore', 'ignore'] })
  } catch (_) {
    return
  }
  child.on('error', () => {})
  try {
    child.stdin.end(JSON.stringify({ tool, params: params || {}, agent_id: 'opencode' }))
    child.unref()
  } catch (_) {}
}

export default {
  id: 'basemem',

  async setup(ctx) {
    const rules = integrityCheckedRules(loadRules())
    const projectName = resolveProjectName([ctx?.location?.directory, process.env.PWD, process.cwd()])

    let bootstrapCache
    const bootstrap = () => {
      if (bootstrapCache !== undefined) return bootstrapCache
      const memContext = fetchMemContext(projectName)
      let text = ''
      if (memContext) text += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`
      if (rules) text += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${rules}\n</EXTREMELY_IMPORTANT>`
      bootstrapCache = text
      return text
    }

    // The context hook fires on every model call, so per-session work is tracked here.
    const bootstrapped = new Set()
    const stopPending = new Set()

    const onModelRequest = (event) => {
      try {
        markActive()
        if (event.sessionID && !bootstrapped.has(event.sessionID)) {
          bootstrapped.add(event.sessionID)
          const text = bootstrap()
          if (text) event.system.push({ type: 'text', text })
        }
        if (event.sessionID && stopPending.has(event.sessionID)) {
          event.system.push({ type: 'text', text: STOP_NUDGE })
        }
      } catch (_) {}
    }

    await ctx.session.hook('context', onModelRequest)
    await ctx.session.hook('compaction', onModelRequest)
    await ctx.session.hook('generate', onModelRequest)

    await ctx.session.hook('prompt', (event) => {
      const text = event?.prompt?.text
      if (!text) return
      if (STOP_PHRASES.some((phrase) => text.toLowerCase().includes(phrase))) {
        stopPending.add(event.sessionID)
      }
      if (text.includes('[Memory Reminder]')) return
      let recall = ''
      try {
        recall = fetchPromptContext(text, projectName)
      } catch (_) {}
      event.prompt.text = `${text}\n\n${MEMORY_REMINDER}${recall ? '\n\n<BASEMEM_PROMPT_CONTEXT>\n' + recall + '\n</BASEMEM_PROMPT_CONTEXT>' : ''}`
    })

    await ctx.tool.hook('execute.after', (event) => {
      try {
        const tool = typeof event?.tool === 'string' ? event.tool : ''
        if (tool) captureToolUse(tool, event.input)
      } catch (_) {}
    })

    const controller = new AbortController()
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (!event || !event.type) continue
          const sessionID = event.data && event.data.sessionID
          if (event.type === 'session.idle') {
            stopPending.delete(sessionID)
            markStopFired()
          } else if (event.type === 'session.deleted' && sessionID) {
            bootstrapped.delete(sessionID)
            stopPending.delete(sessionID)
          }
        }
      } catch (_) {}
    })()

    return () => controller.abort()
  },
}
