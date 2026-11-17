/**
 * The Orchestrator card's data (src/orchestrator.ts).
 *
 * Two halves:
 *  1. the catalogues must be the ones in the repo, not a copy that drifts:
 *     `TRIGGERS` is checked against TRIGGER_ROLES in
 *     webhook_server/triggers.py, `HANDOFFS` against the table in
 *     docs/hermes-office/AGENT-HANDOFFS.md §3;
 *  2. the flow reducer, fed the same events `run_trigger` makes the office
 *     broadcast, must show the route and finish it.
 */

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it, expect } from 'vitest'
import {
  HANDOFFS, MAX_RECENT, STALE_MS, TRIGGERS, initialOrchestratorState, reduceOrchestrator,
  routingFlows, triggerRows, triggerRole,
} from '../src/orchestrator'

const ROOT = join(__dirname, '..')

/** Every `'trigger': 'Role'` inside TRIGGER_ROLES, in file order */
function pythonTriggers(): Array<{ trigger: string; role: string }> {
  const src = readFileSync(join(ROOT, 'webhook_server', 'triggers.py'), 'utf8')
  const start = src.indexOf('TRIGGER_ROLES: dict[str, str] = {')
  expect(start, 'TRIGGER_ROLES not found in triggers.py').toBeGreaterThan(-1)
  const end = src.indexOf('\n}', start)
  return [...src.slice(start, end).matchAll(/'([a-z_]+)':\s*'([A-Za-z]+)'/g)]
    .map(m => ({ trigger: m[1], role: m[2] }))
}

/** The rows of AGENT-HANDOFFS.md §3 */
function docHandoffs(): Array<{ from: string; to: string; reason: string; expects: string }> {
  const src = readFileSync(join(ROOT, 'docs', 'hermes-office', 'AGENT-HANDOFFS.md'), 'utf8')
  const start = src.indexOf('## 3.')
  const end = src.indexOf('## 4.', start)
  expect(start, 'section 3 of AGENT-HANDOFFS.md not found').toBeGreaterThan(-1)
  return src.slice(start, end).split('\n')
    .filter(line => line.startsWith('| ') && !line.includes('| ---'))
    .map(line => line.split('|').map(cell => cell.trim().replace(/`/g, '')))
    .map(cells => cells.filter(Boolean))
    .filter(cells => cells[0] !== 'Dari')
    .map(cells => ({ from: cells[0], to: cells[1], reason: cells[2], expects: cells[4] }))
}

const asAction = (event: object) => event as unknown as Parameters<typeof reduceOrchestrator>[1]
const routed = (agentId: string, status: string) => asAction({ type: 'agent_working', agentId, status })
const done = (agentId: string) => asAction({ type: 'agent_completed', agentId, result: 'new_lead -> Sales' })

describe('the trigger catalogue is the one the sidecar accepts', () => {
  it('all 13 webhook triggers, with the same role, in the same order', () => {
    const fromPython = pythonTriggers()
    expect(fromPython).toHaveLength(13)
    expect(TRIGGERS).toEqual(fromPython)
  })

  it('a trigger outside the table has no role (the card shows ?)', () => {
    expect(triggerRole('new_lead')).toBe('Sales')
    expect(triggerRole('mystery')).toBeNull()
  })
})

describe('the handoff catalogue is the official table, and says it is pending', () => {
  it('every row of AGENT-HANDOFFS.md §3, with its expects', () => {
    const rows = HANDOFFS.map(h => ({ from: h.from, to: h.to, reason: h.reason, expects: h.expects }))
    expect(rows).toEqual(docHandoffs())
  })

  it('all pending while nothing consumes them (W8 adds hermes_bridge/handoff.py)', () => {
    // When W8 lands this file exists and the rows must stop saying "pending":
    // the failure is the reminder, not a bug
    expect(existsSync(join(ROOT, 'hermes_bridge', 'handoff.py'))).toBe(false)
    expect(HANDOFFS.every(h => h.pending === true)).toBe(true)
  })
})

describe('reduceOrchestrator: the flow run_trigger produces', () => {
  it('an Orchestrator saying route_trigger shows up in flight, with its role', () => {
    const state = reduceOrchestrator(initialOrchestratorState(), routed('orchestrator-abc123', 'route_trigger: new_lead (typeform)'), 1000)
    const flows = routingFlows(state)
    expect(flows).toHaveLength(1)
    expect(flows[0]).toMatchObject({ trigger: 'new_lead', role: 'Sales', source: 'typeform', at: 1000 })
  })

  it('its completion files it under recent and counts the trigger', () => {
    let state = reduceOrchestrator(initialOrchestratorState(), routed('orchestrator-abc123', 'route_trigger: new_lead (typeform)'), 1000)
    state = reduceOrchestrator(state, done('orchestrator-abc123'), 1500)
    expect(routingFlows(state)).toHaveLength(0)
    expect(state.recent[0]).toMatchObject({ trigger: 'new_lead', role: 'Sales' })
    expect(state.counts).toEqual({ new_lead: 1 })
    expect(state.lastAt).toBe(1500)
    expect(triggerRows(state).find(r => r.trigger === 'new_lead')!.count).toBe(1)
  })

  it('a trigger nobody mapped is still shown, with ? for its role', () => {
    const state = reduceOrchestrator(initialOrchestratorState(), routed('o1', 'route_trigger: mystery (chat)'), 10)
    expect(routingFlows(state)[0]).toMatchObject({ trigger: 'mystery', role: '?', source: 'chat' })
  })

  it('other messages on the Orchestrator change nothing', () => {
    const state = reduceOrchestrator(initialOrchestratorState(), routed('o1', 'thinking about leads'), 10)
    expect(state).toEqual(initialOrchestratorState())
  })

  it('an unrelated event returns the same object, so the page does not re-render', () => {
    const state = reduceOrchestrator(initialOrchestratorState(), routed('o1', 'route_trigger: new_lead (webhook)'), 10)
    expect(reduceOrchestrator(state, asAction({ type: 'health' }), 20)).toBe(state)
  })

  it('a route whose completion was lost is dropped after STALE_MS, not kept forever', () => {
    const state = reduceOrchestrator(initialOrchestratorState(), routed('o1', 'route_trigger: support_ticket (webhook)'), 1000)
    expect(routingFlows(state)).toHaveLength(1)
    const later = reduceOrchestrator(state, asAction({ type: 'health' }), 1000 + STALE_MS + 1)
    expect(routingFlows(later)).toHaveLength(0)
  })

  it('recent keeps the newest MAX_RECENT routes', () => {
    let state = initialOrchestratorState()
    for (let i = 0; i < MAX_RECENT + 3; i++) {
      state = reduceOrchestrator(state, routed(`o${i}`, 'route_trigger: new_lead (webhook)'), i * 10)
      state = reduceOrchestrator(state, done(`o${i}`), i * 10 + 1)
    }
    expect(state.recent).toHaveLength(MAX_RECENT)
    expect(state.counts.new_lead).toBe(MAX_RECENT + 3)
  })
})
