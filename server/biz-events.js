/**
 * biz-events.js - the business team's surfaces on the office server.
 *
 * 1. `biz_metrics` (Express): counters and gauges the business agents report.
 *    One row per (key, day) so "today" needs no midnight reset job — a new day
 *    is a new row (docs/hermes-office/DB-SCHEMA.md §2).
 * 2. `approval_response` (WebSocket): the one new message from the UI. A
 *    permission card's button is relayed to the FastAPI sidecar, where
 *    `bridge.wait_for_approval()` polls for it (docs/hermes-office/API-REFERENCE.md §4).
 * 3. `bizSlashCommand` (chat): the business slash commands the chat panel types —
 *    `/design`, `/pending-items`, `/approve` — are relayed to the sidecar's
 *    `POST /command`, because the work lives in Python (W7). Nothing is
 *    interpreted here: the reply is whatever the sidecar's agent said.
 *
 * Loaded by server/index.js, which passes in its `db`, `broadcast` and token
 * guard: this module owns no connection and no server of its own.
 */

/** Where the FastAPI sidecar listens; the same name the Python side reads */
const SIDECAR_URL = (process.env.SIDECAR_URL || 'http://127.0.0.1:8765').replace(/\/+$/, '')

/** Keys the panel draws as a current value, not a running total (DB-SCHEMA.md §2) */
export const GAUGE_KEYS = new Set(['tickets_pending', 'sla_avg_response_min', 'sla_breach_count'])

/** A metrics payload is a handful of counters, never a bulk import */
const MAX_KEYS = 32
const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/

/** `approval_response` is tiny: an id, a decision label */
const MAX_WS_BYTES = 512
const AGENT_ID_RE = /^[A-Za-z0-9._-]{1,64}$/

/** The local day, so a report after midnight starts a fresh row */
export function dayKey(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/**
 * Mount `GET/POST /biz-metrics` and create the table they use.
 * @param {import('express').Express} app the office's Express app
 * @param {import('better-sqlite3').Database} db the office DB (chat.db)
 * @param {(payload: object) => void} broadcast the server's WebSocket broadcast
 * @param {{requireToken?: Function, activeAgents?: () => string[]}} [deps]
 *   `requireToken` guards the write (the office's own bearer check) and
 *   `activeAgents` names the agents to show next to the numbers (the server
 *   reads them from its live snapshot; they are never stored in the DB).
 */
export function registerBizRoutes(app, db, broadcast, { requireToken = (_req, _res, next) => next(), activeAgents = () => [] } = {}) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS biz_metrics (
      key TEXT NOT NULL, day TEXT NOT NULL,
      value INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
      PRIMARY KEY (key, day)
    );
    CREATE INDEX IF NOT EXISTS idx_biz_metrics_day ON biz_metrics (day);
  `)

  const upsertDelta = db.prepare(`
    INSERT INTO biz_metrics (key, day, value, updated_at) VALUES (?, ?, ?, ?)
    ON CONFLICT(key, day) DO UPDATE SET
      value = value + excluded.value, updated_at = excluded.updated_at
  `)
  const upsertGauge = db.prepare(`
    INSERT INTO biz_metrics (key, day, value, updated_at) VALUES (?, ?, ?, ?)
    ON CONFLICT(key, day) DO UPDATE SET
      value = excluded.value, updated_at = excluded.updated_at
  `)
  const write = db.transaction((entries) => {
    const now = Date.now()
    const day = dayKey()
    for (const [key, value] of entries) {
      ;(GAUGE_KEYS.has(key) ? upsertGauge : upsertDelta).run(key, day, value, now)
    }
  })

  app.post('/biz-metrics', requireToken, (req, res) => {
    const { delta } = req.body || {}
    if (!delta || typeof delta !== 'object' || Array.isArray(delta)) {
      return res.status(400).json({ error: 'delta must be an object of key: integer' })
    }
    const entries = []
    for (const [key, raw] of Object.entries(delta).slice(0, MAX_KEYS)) {
      // A bad key is skipped, not a 400: one agent's typo must not stop the others
      if (!KEY_RE.test(key)) continue
      const value = Number(raw)
      if (!Number.isFinite(value)) continue
      entries.push([key, Math.trunc(value)])
    }
    if (entries.length) write(entries)

    const metrics = getBizMetrics(db, activeAgents)
    broadcast({ type: 'biz_metric_update', metrics })
    res.json({ ok: true })
  })

  app.get('/biz-metrics', (_req, res) => res.json(getBizMetrics(db, activeAgents)))
}

/**
 * The shape the panel reads, for today only: counters, gauges, who is working.
 * @param {import('better-sqlite3').Database} db the office DB
 * @param {() => string[]} [activeAgents] the agents to list
 * @returns {object} `{ today, sla, agents_active, last_updated }`
 */
export function getBizMetrics(db, activeAgents = () => []) {
  const rows = db.prepare('SELECT key, value FROM biz_metrics WHERE day = ?').all(dayKey())
  const all = Object.fromEntries(rows.map(r => [r.key, r.value]))
  let agents = []
  try { agents = activeAgents() ?? [] } catch { agents = [] }
  return {
    today: {
      leads_qualified: all.leads_qualified ?? 0,
      emails_sent: all.emails_sent ?? 0,
      tickets_resolved: all.tickets_resolved ?? 0,
      tickets_pending: all.tickets_pending ?? 0,
      crm_updates: all.crm_updates ?? 0,
      refunds_processed: all.refunds_processed ?? 0,
      chargebacks: all.chargebacks ?? 0,
    },
    sla: {
      avg_response_min: all.sla_avg_response_min ?? 0,
      breach_count: all.sla_breach_count ?? 0,
    },
    agents_active: agents,
    last_updated: new Date().toISOString(),
  }
}

/**
 * Relay one `approval_response` from the office UI to the sidecar, where the
 * agent waiting on that card picks it up. Everything else on the socket is
 * left to the office's own handler.
 * @param {Buffer | string} data the raw frame
 * @param {{trusted?: boolean}} [options] `trusted` comes from the handshake;
 *   a read-only page may look at the office but not decide for an agent
 * @returns {Promise<boolean>} true when the frame was an approval response
 */
/** The business commands the chat accepts (docs/hermes-office/API-REFERENCE.md §6) */
export const BIZ_SLASH_COMMANDS = [
  '/design',
  '/pending-items',
  '/approve',
  '/revenue',
  '/payments',
  '/subscriptions',
  '/refunds',
  '/chargeback',
  '/security',
  '/takedown',
]

/** One command line, so `/designfoo` stays an ordinary chat message */
const BIZ_COMMAND_RE =
  /^\/(design|pending-items|approve|revenue|payments|subscriptions|refunds|chargeback|security|takedown)(?:\s|$)/

/** A chat line is short; the sidecar clamps again on its own side */
const MAX_COMMAND_CHARS = 200

/**
 * Relay one business slash command to the sidecar and return its reply.
 *
 * Resolves to `null` when the line is not one of the business commands, so
 * `POST /chat` can fall through to its base commands and then to a plain chat
 * message. A sidecar that is down answers in the chat with the command named —
 * a command that silently did nothing is the failure this avoids.
 *
 * @param {string} text the line typed in the chat panel
 * @returns {Promise<string|null>} the chat line to show, or null
 */
export async function bizSlashCommand(text) {
  const line = typeof text === 'string' ? text.trim().slice(0, MAX_COMMAND_CHARS) : ''
  if (!BIZ_COMMAND_RE.test(line)) return null
  const cmd = line.split(/\s+/)[0]
  try {
    const res = await fetch(`${SIDECAR_URL}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: line }),
      signal: AbortSignal.timeout(30_000),
    })
    if (!res.ok) {
      console.warn(`[biz-events] sidecar answered ${res.status} for ${cmd}`)
      return `⚠️ Sidecar menjawab ${res.status} — ${cmd} tidak dijalankan`
    }
    const body = await res.json().catch(() => ({}))
    const reply = typeof body?.reply === 'string' ? body.reply.trim() : ''
    return reply || `✓ ${cmd} dikirim ke sidecar`
  } catch (err) {
    console.warn('[biz-events] sidecar unreachable:', err.message)
    return `⚠️ Sidecar tidak bisa dihubungi — ${cmd} tidak dijalankan`
  }
}

export async function handleBizWsMessage(data, { trusted = false } = {}) {
  if (!trusted) return false
  const raw = Buffer.isBuffer(data) ? data : Buffer.from(String(data))
  if (raw.length > MAX_WS_BYTES) return false
  let msg
  try { msg = JSON.parse(raw.toString('utf8')) } catch { return false }
  if (msg?.type !== 'approval_response') return false

  const agentId = typeof msg.agentId === 'string' ? msg.agentId : ''
  const decision = typeof msg.decision === 'string' ? msg.decision.trim().slice(0, 80) : ''
  if (!AGENT_ID_RE.test(agentId) || !decision) return false

  try {
    const res = await fetch(`${SIDECAR_URL}/approval-callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agentId, decision }),
      signal: AbortSignal.timeout(3000),
    })
    if (!res.ok) console.warn(`[biz-events] sidecar answered ${res.status} for ${agentId}`)
  } catch (err) {
    console.warn('[biz-events] sidecar unreachable:', err.message)
  }
  return true
}
