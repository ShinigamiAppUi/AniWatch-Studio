/**
 * bizApproval.ts — the business team's permission cards.
 *
 * A business agent raises its hand (`hermes_bridge.bridge.agent_waiting`) and
 * the office shows a card with one button per option. The button sends
 * `approval_response` over the WebSocket; the server relays it to the FastAPI
 * sidecar (`server/biz-events.js`), where `bridge.wait_for_approval()` picks it
 * up. Nothing here talks HTTP: the card is only the answer, not the wait.
 *
 * Kept out of the office reducer on purpose: a card is not a character. The
 * office reducer still gets the `agent_waiting` event, so the agent's bubble
 * shows the raised hand (src/officeReducer.ts).
 *
 * Cards live only as long as the browser session: the server does not store
 * them, so a reload drops the ones still open. An agent that is truly waiting
 * sends nothing new until it is answered or times out — reload the page only
 * when you can answer in the terminal instead.
 */

import { BUSINESS_AGENT_CONFIGS, type OfficeEvent } from './types'

/** Role keys lowercased once, so an id can be matched without guessing capitals */
const ROLE_BY_LOWER = new Map<string, string>(
  Object.keys(BUSINESS_AGENT_CONFIGS).map(role => [role.toLowerCase(), role]),
)

/** The 6 hex digits `bridge.agent_start` appends to every business agent id */
const ID_SUFFIX = /-[0-9a-f]{6}$/i

/**
 * `paymentagent-d4d556` -> `PaymentAgent`, `seo-b63366` -> `SEO`.
 *
 * The bridge builds every id as `{role.toLowerCase()}-{6 hex}`
 * (`hermes_bridge/bridge.py`), so a role key is *not* recoverable by
 * capitalising the slug: `paymentagent` would read `Paymentagent`, which is not
 * a key in `BUSINESS_AGENT_CONFIGS`, and the card would quietly fall back to the
 * default colour and ✋. Matching the table case-insensitively is what keeps the
 * camelCase roles (PaymentAgent, QualityChecker, …) and the acronyms (SEO,
 * DMCA) on their own colour, emoji and name.
 *
 * An id that matches no role is still humanised (`agent-w1` -> `Agent`) so a
 * stranger shows something readable instead of nothing.
 */
export function roleFromAgentId(agentId: string): string {
  const raw = String(agentId ?? '').trim()
  if (!raw) return ''
  // A bridge id ends in its hex suffix; any other id only offers the segment
  // before the first dash (`agent-w1`, `main-s-…`), which is the old behaviour
  const slug = (ID_SUFFIX.test(raw) ? raw.replace(ID_SUFFIX, '') : raw.split('-')[0]).toLowerCase()
  if (!slug) return raw
  const known = ROLE_BY_LOWER.get(slug)
  if (known) return known
  return slug.charAt(0).toUpperCase() + slug.slice(1)
}

/** One card: an agent, what it is asking, and the buttons it offered. */
export interface BizApproval {
  agentId: string
  message: string
  options: string[]
  /** The button clicked here, until the agent moves on (optimistic disable) */
  sent?: string
}

export type BizApprovalAction =
  | OfficeEvent
  | { type: 'biz_approval_sent'; agentId: string; decision: string }

/** The events this reducer owns (App hands them here instead of the office reducer) */
export const BIZ_APPROVAL_EVENT_TYPES = new Set(['agent_waiting', 'agent_approval_done'])

export function isBizApprovalEvent(action: { type: string }): boolean {
  return BIZ_APPROVAL_EVENT_TYPES.has(action.type)
}

/** A card's message is one line; long ones are cut rather than growing the stack */
export const MAX_MESSAGE = 240
/** Six buttons is what a card can show without becoming a dialog */
export const MAX_OPTIONS = 6

function cleanMessage(message: unknown): string {
  return String(message ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_MESSAGE)
}

function cleanOptions(options: unknown): string[] {
  if (!Array.isArray(options)) return []
  return options.map(o => String(o ?? '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, MAX_OPTIONS)
}

/**
 * One transition of the card stack.
 *
 * - `agent_waiting` adds a card (or replaces the one for that agent: a second
 *   question supersedes the first, which is what the bridge does too)
 * - `agent_approval_done` (the bridge's answer was taken) and `agent_completed`
 *   (the agent left with the question unanswered) drop it
 * - `biz_approval_sent` disables the buttons while the agent picks the answer up
 */
export function reduceBizApprovals(state: BizApproval[], action: BizApprovalAction): BizApproval[] {
  switch (action.type) {
    case 'agent_waiting': {
      const agentId = typeof action.agentId === 'string' ? action.agentId : ''
      if (!agentId) return state
      const card: BizApproval = {
        agentId,
        message: cleanMessage(action.message),
        options: cleanOptions(action.options),
      }
      const i = state.findIndex(c => c.agentId === agentId)
      if (i < 0) return [...state, card]
      const next = state.slice()
      next[i] = card
      return next
    }
    case 'agent_approval_done':
    case 'agent_completed':
      return state.some(c => c.agentId === action.agentId)
        ? state.filter(c => c.agentId !== action.agentId)
        : state
    case 'biz_approval_sent': {
      const { agentId, decision } = action
      if (!agentId || !decision) return state
      return state.map(c => (c.agentId === agentId ? { ...c, sent: decision } : c))
    }
    default:
      return state
  }
}
