/**
 * orchestrator.ts - what the Orchestrator is doing: the trigger catalogue it
 * routes, the handoff catalogue it will hand over, and the flow of triggers it
 * has actually routed since the page opened.
 *
 * Three sources, kept honest by tests/orchestrator-ui.test.ts:
 *  - `TRIGGERS` mirrors `TRIGGER_ROLES` in webhook_server/triggers.py (the 13
 *    types `POST /webhook` accepts, and the role each one belongs to)
 *  - `HANDOFFS` mirrors the official handoff table in
 *    docs/hermes-office/AGENT-HANDOFFS.md §3
 *  - the flow comes from the office's own events: `run_trigger` draws the
 *    Orchestrator and says `route_trigger: <type> (<source>)`, then finishes it
 *    with `<type> -> <Role>`. Nothing new is fetched.
 *
 * Why the catalogues are data here and not a fetch: the UI can only reach the
 * office server, and the sidecar's trigger table lives in Python. A test reads
 * both sources and fails when they drift, which is cheaper than an endpoint
 * nobody else needs. `HANDOFFS` are all `pending` until W8 adds
 * `hermes_bridge/handoff.py`; the test watches for that file and fails when it
 * appears without the table being updated.
 */

import type { OfficeAction } from './officeReducer'

/** One `type` in a webhook body, and the role key that handles it */
export interface TriggerRoute {
  trigger: string
  role: string
}

/** One row of the official handoff table (AGENT-HANDOFFS.md §3) */
export interface HandoffRoute {
  from: string
  to: string
  reason: string
  expects: string
}

/** The 13 triggers `POST /webhook` accepts, in the order the docs list them */
export const TRIGGERS: TriggerRoute[] = [
  { trigger: 'new_lead', role: 'Sales' },
  { trigger: 'form_submit', role: 'Sales' },
  { trigger: 'deal_stage_change', role: 'Sales' },
  { trigger: 'analytics_ready', role: 'Analytics' },
  { trigger: 'content_schedule', role: 'SocialMedia' },
  { trigger: 'support_ticket', role: 'Support' },
  { trigger: 'new_email', role: 'Support' },
  { trigger: 'episode_released', role: 'Notifier' },
  { trigger: 'weekly_analytics', role: 'Marketing' },
  { trigger: 'announce_episode', role: 'SocialMedia' },
  { trigger: 'retention_check', role: 'Retention' },
  { trigger: 'chargeback_received', role: 'PaymentAgent' },
  { trigger: 'user_report', role: 'UserReportAgent' },
]

/** The official handoffs: the protocol exists (`hermes_bridge/handoff.py`, W8) */
export const HANDOFFS: HandoffRoute[] = [
  { from: 'Sales', to: 'Marketing', reason: 'lead_converted', expects: 'welcome_email_campaign' },
  { from: 'Sales', to: 'Support', reason: 'meeting_scheduled', expects: 'pre_meeting_brief' },
  { from: 'Marketing', to: 'Support', reason: 'customer_onboarding', expects: 'onboarding_followup' },
  { from: 'Support', to: 'Orchestrator', reason: 'ticket_unresolved', expects: 'escalate_to_human' },
  { from: 'UserReportAgent', to: 'Support', reason: 'report_account', expects: 'handle_billing' },
  { from: 'UserReportAgent', to: 'QualityChecker', reason: 'report_technical', expects: 'recheck_episode' },
  { from: 'PaymentAgent', to: 'RevenueTracker', reason: 'payment_settled', expects: 'record_transaction' },
  { from: 'PaymentAgent', to: 'SecOps', reason: 'chargeback', expects: 'flag_account' },
  { from: 'DMCA', to: 'EpisodeScheduler', reason: 'takedown', expects: 'cancel_schedule' },
  { from: 'Scraper', to: 'Metadata', reason: 'episode_fetched', expects: 'enrich_metadata' },
  { from: 'QualityChecker', to: 'Orchestrator', reason: 'qc_failed', expects: 'retry_or_escalate' },
  { from: 'Orchestrator', to: 'Manusia', reason: 'escalate', expects: 'decide' },
]

/** One trigger on its way through the Orchestrator, keyed by the Orchestrator's agent id */
export interface OrchestratorFlow {
  agentId: string
  trigger: string
  role: string
  source: string
  at: number
}

export interface OrchestratorState {
  /** Triggers drawn but not finished yet, by the Orchestrator's agent id */
  routing: Record<string, OrchestratorFlow>
  /** Finished routes, newest first */
  recent: OrchestratorFlow[]
  /** trigger -> how many times it was routed since this page opened */
  counts: Record<string, number>
  /** When the last route finished, null before the first one */
  lastAt: number | null
}

/** Why 6: the card shows a glance, not a log; older ones are in GET /recap */
export const MAX_RECENT = 6

/**
 * Why 2 min: a completion lost to a dropped socket must not leave a route
 * "in flight" forever. `run_trigger` takes milliseconds, so anything this old
 * is stale rather than slow.
 */
export const STALE_MS = 120_000

/** `route_trigger: new_lead (typeform)` — what `run_trigger` puts on the Orchestrator */
const ROUTE_RE = /^route_trigger:\s*(\S+)\s*\(([\w-]+)\)$/

export function initialOrchestratorState(): OrchestratorState {
  return { routing: {}, recent: [], counts: {}, lastAt: null }
}

/** The role a trigger belongs to, or null when it is not one of the 13 */
export function triggerRole(trigger: string): string | null {
  return TRIGGERS.find(t => t.trigger === trigger)?.role ?? null
}

/** The routes in flight, oldest first (one card line each) */
export function routingFlows(state: OrchestratorState): OrchestratorFlow[] {
  return Object.values(state.routing).sort((a, b) => a.at - b.at)
}

/** The catalogue with its live count, for the card's trigger list */
export function triggerRows(state: OrchestratorState): Array<TriggerRoute & { count: number }> {
  return TRIGGERS.map(t => ({ ...t, count: state.counts[t.trigger] ?? 0 }))
}

/** Drop route entries that never finished (lost socket, sidecar died) */
function prune(state: OrchestratorState, now: number): Record<string, OrchestratorFlow> {
  let changed = false
  const routing: Record<string, OrchestratorFlow> = {}
  for (const [id, flow] of Object.entries(state.routing)) {
    if (now - flow.at > STALE_MS) { changed = true; continue }
    routing[id] = flow
  }
  return changed ? routing : state.routing
}

/**
 * One pure transition. Returns the same object when the event says nothing
 * about the Orchestrator, so App.tsx's setState bails out instead of
 * re-rendering the whole page on every office event.
 */
export function reduceOrchestrator(state: OrchestratorState, event: OfficeAction, now: number): OrchestratorState {
  switch (event.type) {
    case 'agent_working': {
      const id = event.agentId
      const match = ROUTE_RE.exec(String(event.status ?? '').trim())
      if (!id || !match) break
      // The Orchestrator is the only one that says `route_trigger:`; a role
      // that is not in the table is still shown, with '?' for its target
      const [, trigger, source] = match
      const flow: OrchestratorFlow = { agentId: id, trigger, role: triggerRole(trigger) ?? '?', source, at: now }
      return { ...state, routing: { ...prune(state, now), [id]: flow } }
    }
    case 'agent_completed': {
      const id = event.agentId
      const flow = id ? state.routing[id] : undefined
      if (!id || !flow) break
      const routing = { ...state.routing }
      delete routing[id]
      return {
        ...state,
        routing: prune({ ...state, routing }, now),
        recent: [flow, ...state.recent].slice(0, MAX_RECENT),
        counts: { ...state.counts, [flow.trigger]: (state.counts[flow.trigger] ?? 0) + 1 },
        lastAt: now,
      }
    }
  }
  // A stale entry can still be cleared by an unrelated event: an Orchestrator
  // that dies without a completion should not sit in "routing" forever
  const routing = prune(state, now)
  return routing === state.routing ? state : { ...state, routing }
}

/** The handoffs as the card draws them: the official table, now enforced by the protocol */
export function handoffRows(): HandoffRoute[] {
  return HANDOFFS
}
