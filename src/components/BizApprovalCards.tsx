/**
 * BizApprovalCards — the business team's raised hands, one card each.
 *
 * A card names the agent (colour and emoji from BUSINESS_AGENT_CONFIGS), what
 * it is asking, and one button per option it offered. The button sends
 * `approval_response` over the office WebSocket and disables at once; the card
 * itself goes when the bridge says the answer was taken (`agent_approval_done`)
 * or the agent leaves (`agent_completed`).
 *
 * A read-only page (no office token) still sees the card — the office is
 * watchable — but gets no buttons: the server relays a decision only from a
 * trusted socket, so a button here would do nothing.
 */

import React from 'react'
import '../styles/biz-approval.css'
import { BUSINESS_AGENT_CONFIGS, isBusinessRole } from '../types'
import type { BizApproval } from '../bizApproval'

interface BizApprovalCardsProps {
  cards: BizApproval[]
  /** The page has no office token: show the cards, offer no answers */
  readOnly?: boolean
  onAnswer: (agentId: string, decision: string) => void
}

const BizApprovalCards: React.FC<BizApprovalCardsProps> = ({ cards, readOnly = false, onAnswer }) => {
  if (cards.length === 0) return null
  return (
    <div className="biz-approvals" role="region" aria-label="Business approvals">
      {cards.map(card => {
        const role = roleOf(card.agentId)
        const cfg = isBusinessRole(role) ? BUSINESS_AGENT_CONFIGS[role] : null
        const colour = cfg?.color ?? '#f59e0b'
        const emoji = cfg?.emoji ?? '✋'
        return (
          <div key={card.agentId} className="biz-approval" style={{ borderColor: colour }}>
            <div className="biz-approval-head">
              <span className="biz-approval-emoji" aria-hidden>{emoji}</span>
              <span className="biz-approval-agent" style={{ color: colour }}>{roleOf(card.agentId)}</span>
              <span className="biz-approval-tag">needs approval</span>
            </div>
            <p className="biz-approval-message">{card.message || 'Waiting for a decision'}</p>
            {readOnly ? (
              <p className="biz-approval-readonly">Read-only page — answer in the terminal or with the office token.</p>
            ) : (
              <div className="biz-approval-buttons">
                {(card.options.length ? card.options : ['Approve', 'Reject']).map(option => (
                  <button
                    key={option}
                    type="button"
                    className="biz-approval-button"
                    disabled={!!card.sent}
                    aria-pressed={card.sent === option}
                    onClick={() => onAnswer(card.agentId, option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
            {card.sent && <p className="biz-approval-sent">Sent: {card.sent}</p>}
          </div>
        )
      })}
    </div>
  )
}

/** `scraper-a1b2c3` -> `Scraper`: the bridge's id is the role, lowercased */
function roleOf(agentId: string): string {
  const slug = String(agentId || '').split('-')[0]
  if (!slug) return agentId
  return slug.charAt(0).toUpperCase() + slug.slice(1)
}

export default BizApprovalCards
