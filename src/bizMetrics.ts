/**
 * bizMetrics.ts - the business team's numbers: GET /biz-metrics, which
 * answers today's counters, the SLA figures and who is working right now.
 *
 * Why it exists: the sidecar counts these from the business events it already
 * records, and the office had no way to show them — the numbers were only
 * visible to someone who curled the endpoint. The status strip's "biz" button
 * opens them (src/components/BizMetricsPanel.tsx).
 *
 * Two sources, one shape: the panel fetches the endpoint when it opens, and
 * `biz_metric_update` (broadcast by the sidecar after every recorded event)
 * carries the same object, so the panel updates without a poll. Both go
 * through `parseBizMetrics`, because a number on screen should never be
 * `NaN`, `undefined` or a string from a half-written payload.
 */

import { officeHttpBase } from './serverUrl'
import { officeAuthHeaders } from './officeAuth'

/** Today's counters, all counts of events recorded since local midnight */
export interface BizMetricsToday {
  leads_qualified: number
  emails_sent: number
  tickets_resolved: number
  tickets_pending: number
  crm_updates: number
  refunds_processed: number
  chargebacks: number
}

export interface BizMetricsSla {
  /** Mean first-response time of the resolved tickets, in minutes */
  avg_response_min: number
  breach_count: number
}

/** What GET /biz-metrics answers and what `biz_metric_update` carries */
export interface BizMetrics {
  today: BizMetricsToday
  sla: BizMetricsSla
  /** Roles with a character in the office right now, '' entries already dropped */
  agents_active: string[]
  /** ISO timestamp of the last recorded business event */
  last_updated: string
}

export type BizTone = 'plain' | 'good' | 'bad' | 'dim'

/** A row of the panel: label, value as shown, and a tone for the value */
export interface BizMetricRow {
  key: string
  label: string
  value: string
  tone: BizTone
}

const TODAY_KEYS: Array<keyof BizMetricsToday> = [
  'leads_qualified', 'emails_sent', 'tickets_resolved', 'tickets_pending',
  'crm_updates', 'refunds_processed', 'chargebacks',
]

/** Why 12: the panel has room for a dozen names; more is a list, not a glance */
export const MAX_ACTIVE_AGENTS = 12

/** A count as the panel can trust it: a whole number, never negative, never NaN */
function count(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return 0
  return Math.trunc(n)
}

/** All-zero metrics, for the moment before the first answer arrives */
export function emptyBizMetrics(now: number = Date.now()): BizMetrics {
  return {
    today: {
      leads_qualified: 0, emails_sent: 0, tickets_resolved: 0,
      tickets_pending: 0, crm_updates: 0, refunds_processed: 0, chargebacks: 0,
    },
    sla: { avg_response_min: 0, breach_count: 0 },
    agents_active: [],
    last_updated: new Date(now).toISOString(),
  }
}

/**
 * Read a /biz-metrics body or a `biz_metric_update` payload.
 *
 * Tolerant on purpose: a missing section reads as zero, and a count that is
 * not a finite number is 0 rather than NaN, so an older or partial payload
 * still shows something true. Only a payload that is not an object at all
 * is refused (null), which is what keeps a stray broadcast from blanking the
 * panel.
 */
export function parseBizMetrics(payload: unknown): BizMetrics | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const body = payload as Record<string, unknown>
  const todayRaw = (body.today && typeof body.today === 'object' ? body.today : {}) as Record<string, unknown>
  const slaRaw = (body.sla && typeof body.sla === 'object' ? body.sla : {}) as Record<string, unknown>

  const today = {} as BizMetricsToday
  for (const key of TODAY_KEYS) today[key] = count(todayRaw[key])

  const seen = new Set<string>()
  const agents: string[] = []
  for (const name of Array.isArray(body.agents_active) ? body.agents_active : []) {
    if (typeof name !== 'string') continue
    const trimmed = name.trim()
    if (!trimmed || seen.has(trimmed)) continue
    seen.add(trimmed)
    agents.push(trimmed)
    if (agents.length === MAX_ACTIVE_AGENTS) break
  }

  return {
    today,
    sla: { avg_response_min: count(slaRaw.avg_response_min), breach_count: count(slaRaw.breach_count) },
    agents_active: agents,
    last_updated: typeof body.last_updated === 'string' && body.last_updated ? body.last_updated : new Date().toISOString(),
  }
}

/** Fetch the counters. Null when the sidecar is not answering or answers an error. */
export async function fetchBizMetrics(): Promise<BizMetrics | null> {
  try {
    // Why the auth headers: through a proxy (Tailscale, phone mode) the office
    // server wants the token in a header (src/officeAuth.ts)
    const res = await fetch(`${officeHttpBase()}/biz-metrics`, {
      signal: AbortSignal.timeout(3000),
      headers: officeAuthHeaders(),
    })
    if (!res.ok) return null
    return parseBizMetrics(await res.json())
  } catch {
    return null
  }
}

/**
 * The rows the panel draws, in reading order: what the team did today, then
 * the SLA, then who is at work. A count that is zero is dim, a number that
 * wants attention (chargebacks, SLA breaches) is red when it is not zero.
 */
export function bizMetricRows(metrics: BizMetrics): BizMetricRow[] {
  const t = metrics.today
  const positive = (n: number): BizTone => (n > 0 ? 'good' : 'dim')
  return [
    { key: 'leads_qualified', label: 'Leads', value: String(t.leads_qualified), tone: positive(t.leads_qualified) },
    { key: 'emails_sent', label: 'Emails', value: String(t.emails_sent), tone: positive(t.emails_sent) },
    { key: 'tickets_resolved', label: 'Tickets resolved', value: String(t.tickets_resolved), tone: positive(t.tickets_resolved) },
    { key: 'tickets_pending', label: 'Tickets pending', value: String(t.tickets_pending), tone: t.tickets_pending > 0 ? 'plain' : 'dim' },
    { key: 'crm_updates', label: 'CRM updates', value: String(t.crm_updates), tone: positive(t.crm_updates) },
    { key: 'refunds_processed', label: 'Refunds', value: String(t.refunds_processed), tone: t.refunds_processed > 0 ? 'plain' : 'dim' },
    { key: 'chargebacks', label: 'Chargebacks', value: String(t.chargebacks), tone: t.chargebacks > 0 ? 'bad' : 'good' },
    { key: 'avg_response_min', label: 'SLA avg', value: `${metrics.sla.avg_response_min} min`, tone: 'plain' },
    { key: 'breach_count', label: 'SLA breaches', value: String(metrics.sla.breach_count), tone: metrics.sla.breach_count > 0 ? 'bad' : 'good' },
    { key: 'agents_active', label: 'Working now', value: String(metrics.agents_active.length), tone: metrics.agents_active.length > 0 ? 'plain' : 'dim' },
  ]
}
