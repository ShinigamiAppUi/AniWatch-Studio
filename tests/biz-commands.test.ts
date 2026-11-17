/**
 * The business slash commands' relay (server/biz-events.js).
 *
 * The work itself is Python (`webhook_server/commands.py`, checked in
 * `hermes_agents.selfcheck`); what this file guards is the office side of the
 * door: only the three commands go to the sidecar, an ordinary line never does,
 * and a sidecar that is down says which command did not run instead of looking
 * like a command that quietly worked.
 */

import { afterEach, describe, it, expect, vi } from 'vitest'
import { BIZ_SLASH_COMMANDS, bizSlashCommand } from '../server/biz-events.js'

const stubFetch = (impl: (...args: unknown[]) => unknown) => {
  const fn = vi.fn(impl)
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BIZ_SLASH_COMMANDS', () => {
  it('is the commands W7 and W9 add, as API-REFERENCE.md §6 lists them', () => {
    expect(BIZ_SLASH_COMMANDS).toEqual([
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
    ])
  })
})

describe('bizSlashCommand', () => {
  it('relays /design and shows the sidecar reply', async () => {
    const fetchFn = stubFetch(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ handled: true, ok: true, reply: '🎨 pm-1 border/neon siap' }),
    }))

    await expect(bizSlashCommand('/design border neon')).resolves.toBe('🎨 pm-1 border/neon siap')
    const [url, init] = fetchFn.mock.calls[0] as [string, { body: string; method: string }]
    expect(url).toContain('/command')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ text: '/design border neon' })
  })

  it('relays /approve with its id and /pending-items with no argument', async () => {
    const fetchFn = stubFetch(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ reply: '🚀 pm-1 live' }),
    }))

    await bizSlashCommand('/approve pm-1')
    await bizSlashCommand('/pending-items')
    const bodies = fetchFn.mock.calls.map(([, init]) => JSON.parse((init as { body: string }).body).text)
    expect(bodies).toEqual(['/approve pm-1', '/pending-items'])
  })

  it('leaves every other line alone: base commands and plain chat are not relayed', async () => {
    const fetchFn = stubFetch(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }))

    for (const line of ['/status', '/clear', '/designfoo', 'halo tim', '', '/designx border']) {
      await expect(bizSlashCommand(line)).resolves.toBeNull()
    }
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('a failing sidecar names the command that did not run', async () => {
    stubFetch(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) }))
    await expect(bizSlashCommand('/design')).resolves.toContain('/design tidak dijalankan')
  })

  it('an unreachable sidecar is a message, not an exception', async () => {
    stubFetch(() => Promise.reject(new Error('ECONNREFUSED')))
    const reply = await bizSlashCommand('/pending-items')
    expect(reply).toContain('tidak bisa dihubungi')
    expect(reply).toContain('/pending-items')
  })

  it('an empty reply still answers, so the person knows the command was taken', async () => {
    stubFetch(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }))
    await expect(bizSlashCommand('/approve pm-9')).resolves.toContain('/approve')
  })

  it('a very long line is clamped before it leaves the office', async () => {
    const fetchFn = stubFetch(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ reply: 'ok' }) }))
    await bizSlashCommand('/design ' + 'x'.repeat(500))
    const init = fetchFn.mock.calls[0][1] as { body: string }
    expect(JSON.parse(init.body).text.length).toBeLessThanOrEqual(200)
  })
})
