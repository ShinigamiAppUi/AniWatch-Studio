/**
 * The business approval card: `agent_waiting` adds a card with its buttons,
 * `agent_approval_done` and `agent_completed` take it away, and the character
 * itself shows the raised hand through the office reducer.
 */

import { describe, expect, it } from 'vitest'
import { reduceBizApprovals, roleFromAgentId, type BizApproval } from '../src/bizApproval'
import { BUSINESS_AGENT_CONFIGS } from '../src/types'
import { reduceOffice, initialOfficeState, type OfficeEnv, type OfficeState } from '../src/officeReducer'
import { createAgent } from '../src/agentManager'
import { findSpot } from '../src/rooms'

const T0 = 1_000_000
const env = (over: Partial<OfficeEnv> = {}): OfficeEnv => ({ now: T0, live: true, computePath: () => [], random: () => 0.5, ...over })

const waiting = (agentId: string, message = 'Refund Rp 149.000?', options = ['Approve', 'Reject']) =>
  ({ type: 'agent_waiting' as const, agentId, message, options })

describe('the business approval cards (src/bizApproval.ts)', () => {
  it('a raised hand becomes one card with one button per option', () => {
    const cards = reduceBizApprovals([], waiting('payment-1'))
    expect(cards).toEqual([{ agentId: 'payment-1', message: 'Refund Rp 149.000?', options: ['Approve', 'Reject'] }])
  })

  it('a second question from the same agent replaces the first card', () => {
    const one = reduceBizApprovals([], waiting('payment-1'))
    const two = reduceBizApprovals(one, waiting('payment-1', 'Lanjutkan?', ['Ya']))
    expect(two).toHaveLength(1)
    expect(two[0]).toMatchObject({ message: 'Lanjutkan?', options: ['Ya'] })
  })

  it('the card goes when the answer was taken, or when the agent leaves', () => {
    const cards: BizApproval[] = [{ agentId: 'a', message: 'm', options: ['x'] }, { agentId: 'b', message: 'm', options: ['x'] }]
    expect(reduceBizApprovals(cards, { type: 'agent_approval_done', agentId: 'a' }).map(c => c.agentId)).toEqual(['b'])
    expect(reduceBizApprovals(cards, { type: 'agent_completed', agentId: 'b' }).map(c => c.agentId)).toEqual(['a'])
  })

  it('a click disables the buttons and keeps the card until the agent moves on', () => {
    const cards = reduceBizApprovals([], waiting('payment-1'))
    const sent = reduceBizApprovals(cards, { type: 'biz_approval_sent', agentId: 'payment-1', decision: 'Approve' })
    expect(sent[0].sent).toBe('Approve')
    expect(sent[0].options).toEqual(['Approve', 'Reject'])
  })

  it('keeps a card to six buttons and a message to one line', () => {
    const many = reduceBizApprovals([], waiting('a', 'x\n\ny', ['1', '2', '3', '4', '5', '6', '7', '8']))
    expect(many[0].options).toEqual(['1', '2', '3', '4', '5', '6'])
    expect(many[0].message).toBe('x y')
  })
})

describe('the character raising its hand (src/officeReducer.ts)', () => {
  it('shows ✋ and the message as the status of an agent already at its desk', () => {
    const desk = findSpot('biz-f2')!.spot
    const seated = createAgent({ id: 'payment-1', name: 'Payment', role: 'PaymentAgent', spot: desk, hiredAt: T0 })
    const agent = { ...seated, state: 'working' as const, position: { ...seated.deskPosition }, pathQueue: [] }
    const { state } = reduceOffice(initialOfficeState([agent], T0), waiting('payment-1'), env())
    const after = state.agents.find(a => a.id === 'payment-1')!
    expect(after.statusText).toBe('✋ Refund Rp 149.000?')
    expect(after.lastFailed).toBe(false)
  })
})

describe('the card finds the role from the bridge id (roleFromAgentId)', () => {
  // `hermes_bridge.bridge.agent_start` builds every business id as
  // `{role.toLowerCase()}-{uuid4[:6]}`; the card has to get the exact key back,
  // because the key is what picks the colour, the emoji and the name
  const bridgeId = (role: string) => `${role.toLowerCase()}-a1b2c3`

  it('every one of the 30 business roles round-trips to its own config key', () => {
    for (const role of Object.keys(BUSINESS_AGENT_CONFIGS)) {
      expect(roleFromAgentId(bridgeId(role)), role).toBe(role)
    }
  })

  it('camelCase roles and acronyms keep their own colour instead of the default amber', () => {
    // The bug this replaces: split('-')[0] + capitalise gave `Paymentagent`,
    // which is not a key, so these cards drew the ✋ fallback
    for (const role of ['PaymentAgent', 'QualityChecker', 'TranslationAgent', 'EpisodeScheduler', 'UserReportAgent', 'SEO', 'DMCA', 'SecOps']) {
      const id = bridgeId(role)
      expect(roleFromAgentId(id), id).toBe(role)
      expect(BUSINESS_AGENT_CONFIGS[roleFromAgentId(id) as keyof typeof BUSINESS_AGENT_CONFIGS].color)
        .toBe(BUSINESS_AGENT_CONFIGS[role as keyof typeof BUSINESS_AGENT_CONFIGS].color)
    }
  })

  it('an id that is not a business role still shows something readable', () => {
    expect(roleFromAgentId('agent-w1')).toBe('Agent')
    expect(roleFromAgentId('scraper-9f8e7d')).toBe('Scraper')
    expect(roleFromAgentId('')).toBe('')
  })
})
