/**
 * The business metrics panel's data (src/bizMetrics.ts): what GET /biz-metrics
 * and a `biz_metric_update` broadcast are allowed to put on screen.
 *
 * The panel itself is React + CSS (not exercised here); everything it decides —
 * which numbers are trusted, which rows exist, and what colour each row gets —
 * lives in the pure module this file tests.
 */

import { describe, it, expect } from 'vitest'
import { bizMetricRows, emptyBizMetrics, parseBizMetrics, MAX_ACTIVE_AGENTS } from '../src/bizMetrics'

/** The body the sidecar's GET /biz-metrics answers */
const body = () => ({
  today: {
    leads_qualified: 3, emails_sent: 11, tickets_resolved: 4, tickets_pending: 2,
    crm_updates: 7, refunds_processed: 1, chargebacks: 0,
  },
  sla: { avg_response_min: 42, breach_count: 0 },
  agents_active: ['Sales', 'Support'],
  last_updated: '2026-11-17T07:03:00.000Z',
})

describe('parseBizMetrics', () => {
  it('reads the whole body, counters as numbers', () => {
    const m = parseBizMetrics(body())!
    expect(m.today.leads_qualified).toBe(3)
    expect(m.today.crm_updates).toBe(7)
    expect(m.sla).toEqual({ avg_response_min: 42, breach_count: 0 })
    expect(m.agents_active).toEqual(['Sales', 'Support'])
    expect(m.last_updated).toBe('2026-11-17T07:03:00.000Z')
  })

  it('a payload that is not an object is refused, so the panel keeps what it has', () => {
    for (const junk of [null, undefined, 'nope', 42, true, []]) expect(parseBizMetrics(junk)).toBeNull()
  })

  it('a missing or broken section reads as zero, never NaN', () => {
    const m = parseBizMetrics({ today: { leads_qualified: 'lots', emails_sent: -4 }, sla: { avg_response_min: Infinity } })!
    expect(m.today.leads_qualified).toBe(0)
    expect(m.today.emails_sent).toBe(0)
    expect(m.today.tickets_resolved).toBe(0)
    expect(m.sla.avg_response_min).toBe(0)
    expect(Number.isNaN(m.sla.avg_response_min)).toBe(false)
  })

  it('agents_active keeps strings only, once each, at most MAX_ACTIVE_AGENTS', () => {
    const m = parseBizMetrics({ agents_active: ['Sales', 'Sales', '', '  ', 7, null, 'Support'] })!
    expect(m.agents_active).toEqual(['Sales', 'Support'])
    const many = Array.from({ length: MAX_ACTIVE_AGENTS + 5 }, (_, i) => `Role${i}`)
    expect(parseBizMetrics({ agents_active: many })!.agents_active).toHaveLength(MAX_ACTIVE_AGENTS)
  })

  it('emptyBizMetrics is all zeros, so the panel can open before the first answer', () => {
    const m = emptyBizMetrics(0)
    expect(bizMetricRows(m).every(r => r.value === '0' || r.value === '0 min')).toBe(true)
    expect(m.agents_active).toEqual([])
  })
})

describe('bizMetricRows', () => {
  it('draws today, then the SLA, then who is working — in that order', () => {
    const rows = bizMetricRows(parseBizMetrics(body())!)
    expect(rows.map(r => r.key)).toEqual([
      'leads_qualified', 'emails_sent', 'tickets_resolved', 'tickets_pending', 'crm_updates',
      'refunds_processed', 'chargebacks', 'avg_response_min', 'breach_count', 'agents_active',
    ])
    expect(rows.map(r => r.label)).toContain('SLA breaches')
    expect(rows.find(r => r.key === 'avg_response_min')!.value).toBe('42 min')
    expect(rows.find(r => r.key === 'agents_active')!.value).toBe('2')
  })

  it('a zero count is dim, a count the team made is green', () => {
    const rows = bizMetricRows(parseBizMetrics(body())!)
    expect(rows.find(r => r.key === 'leads_qualified')!.tone).toBe('good')
    expect(rows.find(r => r.key === 'chargebacks')!.tone).toBe('good')   // zero chargebacks is good
    const quiet = bizMetricRows(emptyBizMetrics())
    expect(quiet.find(r => r.key === 'leads_qualified')!.tone).toBe('dim')
  })

  it('chargebacks and SLA breaches turn red when they are not zero', () => {
    const m = parseBizMetrics({ ...body(), today: { ...body().today, chargebacks: 2 }, sla: { avg_response_min: 90, breach_count: 1 } })!
    const rows = bizMetricRows(m)
    expect(rows.find(r => r.key === 'chargebacks')).toMatchObject({ value: '2', tone: 'bad' })
    expect(rows.find(r => r.key === 'breach_count')).toMatchObject({ value: '1', tone: 'bad' })
  })
})
