/**
 * BizMetricsPanel - the status strip's "biz" popover: today's business
 * counters, the SLA figures and who is working, from GET /biz-metrics
 * (server/biz-events.js) plus the `biz_metric_update` the office server
 * broadcasts after every metric the sidecar posts.
 *
 * It fetches each time it opens and every 30 s while it stays open, the way
 * TodayPanel does, so a page left alone still catches up; a live update that
 * arrives while it is open wins immediately (App.tsx holds it).
 *
 * Numbers only: no office token is needed to read them, so the panel works on
 * a read-only page too.
 */

import React, { useEffect, useRef, useState } from 'react'
import { bizMetricRows, fetchBizMetrics, type BizMetrics } from '../bizMetrics'
import '../styles/settings.css'

// Why 30 s: the sidecar writes these on webhook events; half a minute is well
// inside "did my lead get counted", and GET /biz-metrics reads one row of counters
const REFRESH_MS = 30_000

interface BizMetricsPanelProps {
  onClose: () => void
  /** The button that opened it: a click on it is the toggle, not an outside click */
  anchor: React.RefObject<HTMLElement>
  /** The newest `biz_metric_update` App.tsx has seen, null before the first one */
  live?: BizMetrics | null
}

/** "14:03" for an ISO timestamp, or the raw string when it does not parse */
function updatedLabel(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const BizMetricsPanel: React.FC<BizMetricsPanelProps> = ({ onClose, anchor, live = null }) => {
  const [metrics, setMetrics] = useState<BizMetrics | null>(live)
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // A live broadcast is fresher than the fetch that brought the panel up
  useEffect(() => { if (live) setMetrics(live) }, [live])

  useEffect(() => {
    let alive = true
    const load = () => fetchBizMetrics().then(m => {
      if (!alive) return
      if (m) { setMetrics(m); setFailed(false) } else setFailed(true)
    })
    void load()
    const timer = setInterval(load, REFRESH_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  // Escape or a click elsewhere closes it
  useEffect(() => {
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

  const agents = metrics?.agents_active ?? []

  return (
    <div className="biz-panel office-popover" role="dialog" aria-label="Business metrics" ref={ref} data-testid="biz-panel">
      <div className="op-head">
        <span className="op-title">Business · today</span>
        <button className="op-close" onClick={onClose} aria-label="Close">×</button>
      </div>
      {!metrics && <div className="op-note">{failed ? 'The sidecar is not answering.' : 'Counting…'}</div>}
      {metrics && (
        <dl className="biz-grid">
          {bizMetricRows(metrics).map(row => (
            <React.Fragment key={row.key}>
              <dt>{row.label}</dt>
              <dd className={`tone-${row.tone}`}>{row.value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {agents.length > 0 && (
        <div className="biz-agents" data-testid="biz-agents">
          working: <span>{agents.join(', ')}</span>
        </div>
      )}
      <div className="op-foot">
        {metrics ? `Updated ${updatedLabel(metrics.last_updated)}` : 'GET /biz-metrics'}
      </div>
    </div>
  )
}

export default BizMetricsPanel
