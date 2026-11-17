/**
 * OrchestratorCard - what the Orchestrator is doing: the trigger it is routing
 * right now, the triggers it has routed since the page opened, the 13 it can
 * route at all, and the official handoffs that are still pending.
 *
 * Everything comes from state App.tsx already holds (src/orchestrator.ts reads
 * the office's own events), so the card fetches nothing and works on a
 * read-only page: it is a view, not a client.
 *
 * "Pending" is said out loud rather than hidden: the 13 trigger routes are live
 * (`webhook_server/triggers.py`), but every handoff in AGENT-HANDOFFS.md §3 is
 * waiting on W8, and the card draws them greyed with a `pending` chip instead
 * of pretending they happen.
 */

import React from 'react'
import {
  handoffRows, routingFlows, triggerRows, MAX_RECENT,
  type OrchestratorState,
} from '../orchestrator'
import '../styles/settings.css'

interface OrchestratorCardProps {
  state: OrchestratorState
  onClose: () => void
  /** The button that opened it: a click on it is the toggle, not an outside click */
  anchor: React.RefObject<HTMLElement>
}

/** "4 s", "2 min", "1 h" — the card never needs more precision than that */
function since(at: number, now: number): string {
  const s = Math.max(0, Math.floor((now - at) / 1000))
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} h`
}

const OrchestratorCard: React.FC<OrchestratorCardProps> = ({ state, onClose, anchor }) => {
  const ref = React.useRef<HTMLDivElement>(null)
  const [now, setNow] = React.useState(Date.now())

  // The elapsed label ("routing… 4 s") needs a tick; 1 s is the smallest useful
  React.useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  // Escape or a click elsewhere closes it
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (ref.current?.contains(t) || anchor.current?.contains(t)) return
      onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose, anchor])

  const routing = routingFlows(state)
  const rows = triggerRows(state)
  const routed = rows.reduce((n, r) => n + r.count, 0)
  const recent = state.recent.slice(0, MAX_RECENT)

  return (
    <div className="orch-panel office-popover" role="dialog" aria-label="Orchestrator" ref={ref} data-testid="orch-panel">
      <div className="op-head">
        <span className="op-title">Orchestrator</span>
        <button className="op-close" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="orch-section" data-testid="orch-now">
        {routing.length === 0 && <div className="op-note">idle · nothing to route</div>}
        {routing.map(flow => (
          <div className="orch-row orch-now" key={flow.agentId}>
            <span className="orch-dot" aria-hidden />
            <span className="orch-name">{flow.trigger} → {flow.role}</span>
            <span className="orch-meta">{flow.source} · {since(flow.at, now)}</span>
          </div>
        ))}
      </div>

      {recent.length > 0 && (
        <div className="orch-section">
          <div className="orch-head">recent</div>
          {recent.map(flow => (
            <div className="orch-row" key={`${flow.agentId}-${flow.at}`} data-testid="orch-recent">
              <span className="orch-name">{flow.trigger} → {flow.role}</span>
              <span className="orch-meta">{since(flow.at, now)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="orch-section">
        <div className="orch-head">can route · {rows.length}</div>
        <div className="orch-grid" data-testid="orch-triggers">
          {rows.map(row => (
            <div className={`orch-row${row.count ? '' : ' orch-dim'}`} key={row.trigger}>
              <span className="orch-name">{row.trigger}</span>
              <span className="orch-role">{row.role}</span>
              {row.count > 0 && <span className="orch-count">×{row.count}</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="orch-section">
        <div className="orch-head">handoffs · pending</div>
        <div className="orch-grid orch-handoffs" data-testid="orch-handoffs">
          {handoffRows().map(h => (
            <div className="orch-row orch-dim" key={h.reason}>
              <span className="orch-name">{h.from} → {h.to}</span>
              <span className="orch-chip">pending</span>
            </div>
          ))}
        </div>
      </div>

      <div className="op-foot">
        {routed === 0 ? 'No trigger has been routed since this page opened' : `${routed} routed since this page opened`}
      </div>
    </div>
  )
}

export default OrchestratorCard
