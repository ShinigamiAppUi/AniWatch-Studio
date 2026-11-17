/**
 * The business team in the office: a role from src/types.ts (BUSINESS_AGENT_CONFIGS)
 * is seated at its own `biz-*` desk in its own room, and a dev role is seated
 * exactly as before. This is the contract `hermes_bridge.bridge.agent_start()`
 * relies on: one `agent_spawned` event, the right desk, no dev spot taken.
 */

import { describe, expect, it } from 'vitest'
import { reduceOffice, initialOfficeState, type OfficeEnv, type OfficeState } from '../src/officeReducer'
import { createAgent } from '../src/agentManager'
import { findSpot } from '../src/rooms'
import { BUSINESS_AGENT_CONFIGS, isBusinessRole } from '../src/types'

const T0 = 1_000_000

function env(over: Partial<OfficeEnv> = {}): OfficeEnv {
  return { now: T0, live: true, computePath: () => [], random: () => 0.5, ...over }
}

function emptyOffice(): OfficeState {
  const boss = createAgent({ id: 'boss', name: 'Boss', role: 'boss', spot: { id: 'spot-1', type: 'desk', x: 10, y: 50, facing: 'down' } as never, hiredAt: T0 })
  return initialOfficeState([boss], T0)
}

const spawn = (id: string, role: string) => ({
  type: 'agent_spawned' as const,
  agent: { id, name: role, role, task: 'test' },
})

const agent = (state: OfficeState, id: string) => state.agents.find(a => a.id === id)!

describe('a business role is seated at its own desk', () => {
  it('every business role has a free, distinct desk in its own room', () => {
    const seen = new Set<string>()
    for (const [role, cfg] of Object.entries(BUSINESS_AGENT_CONFIGS)) {
      const found = findSpot(cfg.desk)
      expect(found, `${role} -> ${cfg.desk}`).not.toBeNull()
      expect(found!.room, role).toBe(cfg.room)
      expect(seen.has(cfg.desk), `duplicate desk ${cfg.desk}`).toBe(false)
      seen.add(cfg.desk)
    }
    expect(seen.size).toBe(30)
  })

  it('Scraper appears in the server room at biz-s1, not in the office', () => {
    const { state } = reduceOffice(emptyOffice(), spawn('scraper-t', 'Scraper'), env())
    const a = agent(state, 'scraper-t')
    const desk = findSpot('biz-s1')!.spot
    expect(a.role).toBe('Scraper')
    expect(a.room).toBe('server-room')
    expect(a.assignedRoom).toBe('server-room')
    expect(a.deskPosition).toEqual({ x: desk.x, y: desk.y })
    expect(a.targetPosition).toEqual({ x: desk.x, y: desk.y })
  })

  it('Sales appears in the business suite and Support at its main-office desk', () => {
    const one = reduceOffice(emptyOffice(), spawn('sales-t', 'Sales'), env()).state
    expect(agent(one, 'sales-t').room).toBe('business-suite')
    const two = reduceOffice(one, spawn('support-t', 'Support'), env()).state
    expect(agent(two, 'support-t').room).toBe('main-office')
    const communityDesk = findSpot('biz-m1')!.spot
    expect(agent(two, 'support-t').deskPosition).toEqual({ x: communityDesk.x, y: communityDesk.y })
  })

  it('a dev role keeps the old behaviour: the office, pickSpot', () => {
    const { state } = reduceOffice(emptyOffice(), spawn('dev-t', 'debugger'), env())
    const a = agent(state, 'dev-t')
    expect(isBusinessRole('debugger')).toBe(false)
    expect(a.room).toBe('main-office')
    expect(a.assignedRoom).toBe('main-office')
  })

  it('a second agent of the same role does not take the desk already used', () => {
    const one = reduceOffice(emptyOffice(), spawn('sales-1', 'Sales'), env()).state
    const two = reduceOffice(one, spawn('sales-2', 'Sales'), env()).state
    const first = agent(two, 'sales-1')
    const second = agent(two, 'sales-2')
    expect(second.deskPosition).not.toEqual(first.deskPosition)
  })
})
