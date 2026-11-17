import type { RoomId } from './rooms'
import type { SessionStatus, AgentStatus, MeterTotals } from './meters'
import type { TaskBoardInfo } from './taskBoard'
import type { BizMetrics } from './bizMetrics'

export type AgentState =
  | 'idle'
  | 'walking-to-manager'
  | 'talking-to-manager'
  | 'walking-to-desk'
  | 'working'
  | 'coffee-break'
  | 'completed'
  | 'new-hire'
  | 'changing-room'
  | 'waiting'               // in the lobby by the door until a desk frees up

export interface Position {
  x: number
  y: number
}

export interface Agent {
  id: string
  name: string
  type: 'subagent' | 'mcp'
  role: string
  state: AgentState
  position: Position
  targetPosition: Position
  deskPosition: Position
  room: RoomId              // which room the agent is currently in
  assignedRoom: RoomId      // where their desk is
  assignedSpotId?: string   // which spot they're assigned to
  // Why a second spot: a visitor to another room (src/roomTransfer.ts) keeps its
  // own desk reserved, so the way back can never find it taken
  visitSpotId?: string      // the seat it holds in another room while it is away from its own
  task?: string
  statusText?: string
  spriteFacing?: 'front-left' | 'front-right' | 'rear-left' | 'rear-right'
  color: string
  emoji: string
  hiredAt: number
  pathQueue?: { x: number; y: number }[]  // waypoints to walk through
  unread?: number           // directed agent-to-agent messages not yet read
  sessionId?: string        // the Claude Code session (terminal) this agent works for
  project?: string          // that session's project (basename of its cwd)
  lastFailed?: boolean      // the last agent_working for this agent was a tool failure
  // The per-session Claude (id `main-<sessionId>`) only: what its main thread is doing
  mainState?: MainState     // undefined = not heard from yet
  needsYou?: NeedsYou       // set while mainState is 'needs-you'
  waitingOn?: number        // background workers a finished turn still waits for
  model?: string            // the session's model (session_model / session_started)
  scene?: AgentScene        // a signal's scene on the character that ran the command
  callout?: Callout         // the boss shouting a prompt across the office, and the Claude that heard it
}

/**
 * What a Bash command meant: hooks/agent-tracker.sh classifies the commands
 * that deploy, build, test or push ("Signals") and the server broadcasts
 * one `signal` event per signal, right after the event that carried it.
 */
export type SignalKind =
  | 'deploy_start' | 'deploy_success' | 'deploy_fail'
  | 'build_start' | 'build_ok' | 'build_failed'
  | 'test_start' | 'test_ok' | 'test_failed'
  | 'push' | 'push_done' | 'push_failed'

/** The server's `signal` broadcast (also the snapshot's `signals` entries and GET /signals) */
export interface SignalEvent {
  type: 'signal'
  kind: SignalKind
  /** What it was about: the app, package or directory, else the project */
  target?: string
  /** "3 failing", "2 errors" */
  detail?: string
  /** The first meaningful line of a failure's output */
  error?: string
  exitCode?: number
  /** A push: the branch, and whether it is main / master */
  branch?: string
  toDefault?: boolean
  /** The run was stopped (Esc), not failed */
  interrupted?: boolean
  sessionId?: string
  project?: string
  /** The office worker that ran it (absent on the main thread) */
  agentId?: string
  agentName?: string
  at?: number
  seq?: number
  timestamp?: number
}

/**
 * A scene a signal puts on the character that ran the command: a deploy
 * shipping (until it lands or 10 min pass), a deploy that landed, a red run,
 * a push to main. `until` is when it ends by itself.
 */
export interface AgentScene {
  kind: 'shipping' | 'shipped' | 'red' | 'pushed'
  until: number
  label?: string
}

/**
 * A prompt shouted across the office (src/officeReducer.ts bossShout): the
 * boss's speech bubble (`shout`, the start of the prompt or a bare "!") and
 * the "!" over the Claude it was meant for (`heard`). `seq` is the shout's
 * number, so the timer that clears it cannot clear a newer one.
 */
export interface Callout {
  kind: 'shout' | 'heard'
  text: string
  seq: number
}

/** What a session's main thread (its Claude) is doing — the server's `main.state` */
export type MainState = 'working' | 'waiting' | 'idle' | 'needs-you' | 'error' | 'compacting'

/**
 * `registry`: an unhooked session whose registry status is "waiting" (a dialog or question in its terminal).
 * `elicitation`: an MCP server asked the user something (the Elicitation hook); `summary` is the server's name.
 */
export type NeedsYouKind = 'permission' | 'idle' | 'quota' | 'agent-input' | 'registry' | 'elicitation'

/** Why a session is waiting on a person (session_needs_you / main.needsYou) */
export interface NeedsYou {
  kind: NeedsYouKind
  toolName?: string
  summary?: string
  message?: string
  /** The business approval's button labels (src/bizApproval.ts) */
  options?: string[]
  notificationType?: string
  promptId?: string
  since?: number
}

/**
 * The server's per-session main-thread record. Travels as `main` on the WS
 * snapshot's sessions, GET /sessions and every session_* broadcast. Text
 * fields are '' when the server's `logPrompts` setting is off.
 */
export interface SessionMain {
  state: MainState
  since?: number
  lastPrompt?: string
  lastPromptAt?: number
  lastReply?: string
  lastReplyAt?: number
  waitingOn?: number
  crons?: number
  needsYou?: NeedsYou
  error?: { error: string; detail?: string; since?: number }
  promptId?: string
}

/**
 * A Claude Code PermissionUpdate the dialog suggested (setMode, addRules,
 * addDirectories, ...). Passed through as the server sent it, so "allow and
 * remember" can echo it back verbatim; src/permissions.ts only reads it.
 */
export type PermissionSuggestion = Record<string, unknown>

/**
 * A permission dialog waiting on the office (server/permissions.js): what
 * `permission_request` carries and the WS snapshot lists as pendingPermissions.
 */
export interface PendingPermission {
  id: string
  sessionId: string
  project?: string
  cwd?: string
  sessionTitle?: string
  toolName: string
  summary: string
  /** The Bash command, the file path, or the tool input as compact JSON (≤ 400 chars) */
  detail: string
  suggestions: PermissionSuggestion[]
  permissionMode: string
  promptId?: string
  agentId?: string
  createdAt: number
  /** When the server hands the dialog back to the terminal (extended once the session is known interactive) */
  deadline: number
  status: 'pending' | 'allowed' | 'denied' | 'resolved_elsewhere' | 'expired'
  interactive?: boolean
}

/** One entry of session_turn_end.backgroundTasks (a Stop hook's background_tasks item) */
export interface BackgroundTask {
  id: string
  type: string
  status: string
  description?: string
  /** The office worker this task is, when the server knows it */
  officeId?: string
}

/**
 * A Claude Code session the office knows about — one per terminal. Mirrors
 * the server's GET /sessions entries and session_started/session_ended events.
 */
export interface SessionInfo {
  id: string
  project?: string
  cwd?: string
  title?: string
  model?: string
  source?: string           // startup | resume | compact | clear | fork | implicit
  state: 'active' | 'ended'
  reason?: string           // why it ended
  startedAt?: number
  lastActivityAt?: number
  /** Last main-thread tool status (agent_working with no agentId) and when */
  lastStatus?: string
  lastStatusAt?: number
  /** The server's main-thread record, once it sends one */
  main?: SessionMain
  /**
   * false: known only from Claude Code's session registry (no hook has
   * reported yet — the strip shows it tinted "not hooked", the office seats
   * no Claude for it); true or absent: the hooks report it.
   */
  hooked?: boolean
  /** Its entry in Claude Code's session registry, while its process runs */
  registry?: SessionRegistry
  /** The name `@<name> <prompt>` in the chat queues a prompt for (server/prompt-queue.js mentionName) */
  mention?: string
}

/**
 * What the server keeps of a ~/.claude/sessions/<pid>.json entry (server/
 * sessions.js): presence and status only. `status` is Claude Code's own word
 * (busy | shell | idle | waiting); `name` is the registry display name
 * ("office-7f" derived from the cwd, or what --name / /rename set).
 */
export interface SessionRegistry {
  pid: number
  name?: string
  nameSource?: string
  status?: string
  kind?: string
  version?: string
  startedAt?: number
  statusUpdatedAt?: number
}

/**
 * One entry of the server's `snapshot` message (its activeAgents record).
 * MCP calls are tracked as transient records with a `server` field; they are
 * not office workers.
 */
export interface SnapshotAgent {
  id: string
  name?: string
  role?: string
  task?: string
  state?: string
  status?: string
  unread?: number
  sessionId?: string
  project?: string
  /** An MCP call in flight (server/index.js tracks one record per call): the server called... */
  server?: string
  /** ...and the tool called on it */
  tool?: string
}

/**
 * The server's pipeline health: GET /health, the snapshot's `health` and the
 * `health` broadcast (server/health.js). What the status strip shows.
 */
export interface ServerHealth {
  status: string
  agents: number
  clients: number
  sessions: number
  /** When a Claude Code hook last reached POST /event (ms epoch), null if never since boot */
  lastHookAt: number | null
  /** Hook events accepted since the server started */
  hooksSeen: number
  /** The built UI (dist/) is served from the server's root */
  uiAvailable: boolean
  version: string
  uptimeMs: number
}

export interface OfficeEvent {
  type: 'agent_spawned' | 'agent_working' | 'agent_completed'
    // A business agent's raised hand and the note that its answer was taken
    | 'agent_waiting' | 'agent_approval_done'
    | 'mcp_call' | 'mcp_done' | 'new_hire' | 'chat_message' | 'chat_typing' | 'chat_reaction' | 'chat_seen' | 'inbox_update' | 'variant_change' | 'session_started' | 'session_ended' | 'session_status' | 'agent_status' | 'snapshot'
    // The turn events (UserPromptSubmit, Stop, PermissionRequest/Notification, StopFailure, Pre/PostCompact, CwdChanged, PostModelSwitch),
    // session_main (a server-side change: a hand lowered by a tool result or the timeout) and
    // session_tool_done (main-thread PostToolUse / PostToolBatch, the input that lowers a hand)
    | 'session_prompt' | 'session_turn_end' | 'session_needs_you' | 'session_error' | 'session_compact' | 'session_cwd' | 'session_model'
    | 'session_main' | 'session_tool_done'
    // session_registry: the session's registry entry changed (status, name, attached, gone) — the full session record
    | 'session_registry'
    // A permission dialog waiting on the office, its deadline moving, and its end (src/permissions.ts)
    | 'permission_request' | 'permission_extended' | 'permission_resolved'
    // Pipeline health (the status strip): the server's record, and the socket's own open/close
    | 'health' | 'connection'
    // A session's task list changed (server/tasks.js), or the snapshot's boards (src/taskBoard.ts)
    | 'task_board'
    // The business counters (webhook_server: GET /biz-metrics and the broadcast
    // after every recorded event) — src/bizMetrics.ts, drawn by BizMetricsPanel
    | 'biz_metric_update'
  agent?: Partial<Agent>
  agentId?: string
  status?: string
  result?: string
  // agent_completed: what the Agent tool reported for a foreground subagent
  tokens?: number
  durationMs?: number
  toolUses?: number
  // snapshot: every agent the server knows about (sent on each (re)connect), and the sessions
  activeAgents?: SnapshotAgent[]
  sessions?: SessionInfo[]
  // biz_metric_update: the whole business-metrics object (src/bizMetrics.ts)
  metrics?: BizMetrics
  // snapshot: the permission dialogs waiting on the office, and the token that answers them
  pendingPermissions?: PendingPermission[]
  uiToken?: string
  // permission_request / permission_extended / permission_resolved
  permission?: PendingPermission
  permissionId?: string
  deadline?: number
  decidedBy?: 'office' | 'terminal' | 'timeout'
  // Every session_* broadcast carries the session's main-thread record
  main?: SessionMain
  promptId?: string
  // session_prompt / session_turn_end (their `text` ≤ 2000 is the shared field below, '' when logPrompts is off)
  isWakeup?: boolean
  wakeupAgentId?: string      // the subagent id in the wake-up prompt
  wakeupOfficeId?: string     // that worker's office id, when the server knows it
  wakeupStatus?: string
  backgroundTasks?: BackgroundTask[]
  crons?: number | unknown[]
  stopHookActive?: boolean
  // session_needs_you
  kind?: NeedsYouKind
  toolName?: string
  summary?: string
  message?: string
  /** A business approval's button labels (agent_waiting, src/bizApproval.ts) */
  options?: string[]
  notificationType?: string
  needsYou?: NeedsYou
  // session_tool_done
  batch?: boolean
  count?: number
  // session_error
  error?: string
  detail?: string
  // session_compact
  phase?: 'pre' | 'post'
  trigger?: string
  // session_cwd / session_model
  oldCwd?: string
  fromModel?: string
  switchSource?: string
  // chat_message: the server's row id (chat_reaction / chat_seen refer to it)
  id?: number
  isSystem?: boolean
  role?: string
  // chat_reaction / chat_seen
  messageId?: number
  reactions?: string[]
  // mcp_call
  server?: string
  tool?: string
  // The Claude Code session the event came from (every hook event carries it)
  sessionId?: string
  project?: string
  // session_started / session_ended / session_registry
  cwd?: string
  source?: string
  model?: string
  title?: string
  state?: 'active' | 'ended'
  startedAt?: number
  lastActivityAt?: number
  lastStatus?: string
  lastStatusAt?: number
  // false while only Claude Code's session registry knows the session (no hook has reported)
  hooked?: boolean
  // the session's registry entry; absent once its process has gone
  registry?: SessionRegistry
  // the name a chat @-mention uses for the session (server/prompt-queue.js)
  mention?: string
  timestamp?: number
  // session_status / agent_status: the payroll / electricity / memory feed (src/meters.ts)
  session?: SessionStatus
  statuses?: SessionStatus[]
  totals?: MeterTotals
  removed?: boolean
  agents?: AgentStatus[]
  sender?: string
  text?: string
  // Directed agent-to-agent chat messages
  recipient?: string | null
  recipientId?: string | null
  senderId?: string | null
  msg_type?: string | null
  // inbox_update
  unread?: number
  // agent_working: the tool call errored (PostToolUseFailure)
  failed?: boolean
  // agent_working: auto mode refused the call (PermissionDenied); always with failed
  denied?: boolean
  // variant_change: the server relayed /incident or /all-clear to every client
  // (reason is also why a session_ended session ended)
  variant?: 'none' | 'incident'
  reason?: string
  // health: the server's pipeline record (server/health.js), also carried by the snapshot
  health?: ServerHealth
  // task_board: one session's board (null: no tasks, or the session ended), or
  // every board at once (`boards`, from the snapshot)
  board?: TaskBoardInfo | null
  boards?: TaskBoardInfo[]
  // task_board: which board it is when it is an agent team's (`team:<name>`); a session's own board has none
  boardId?: string
  // connection: the WebSocket opened or closed — dispatched by useAgentSocket, not sent by the server
  socket?: 'open' | 'closed'
}

import { BOSS_CONFIG } from './config'

export const AGENT_CONFIGS: Record<string, { color: string; emoji: string; title: string }> = {
  // The boss — configured via office.config.json. The object itself, not a
  // copy: loadRuntimeConfig (src/config.ts) updates it in place.
  'boss':                  BOSS_CONFIG,
  // Subagents
  'debugger':              { color: '#e74c3c', emoji: '🔍', title: 'Debugger' },
  'code-reviewer':         { color: '#3498db', emoji: '📋', title: 'Reviewer' },
  'frontend-developer':    { color: '#2ecc71', emoji: '🎨', title: 'Frontend' },
  'fullstack-developer':   { color: '#9b59b6', emoji: '⚡', title: 'Fullstack' },
  'test-engineer':         { color: '#f39c12', emoji: '🧪', title: 'Tester' },
  'security-auditor':      { color: '#e67e22', emoji: '🛡️', title: 'Security' },
  'architect-reviewer':    { color: '#1abc9c', emoji: '🏗️', title: 'Architect' },
  'performance-engineer':  { color: '#e91e63', emoji: '🚀', title: 'PerfEng' },
  'devops-engineer':       { color: '#607d8b', emoji: '🔧', title: 'DevOps' },
  'database-architect':    { color: '#795548', emoji: '🗄️', title: 'DBA' },
  'typescript-pro':        { color: '#3178c6', emoji: '📘', title: 'TS Pro' },
  'ai-engineer':           { color: '#ff6f00', emoji: '🤖', title: 'AI Eng' },
  'prompt-engineer':       { color: '#ab47bc', emoji: '✍️', title: 'Prompts' },
  'general-purpose':       { color: '#78909c', emoji: '👤', title: 'General' },
  'Explore':               { color: '#4caf50', emoji: '🔭', title: 'Explorer' },
  // MCPs
  'github':                { color: '#f0f0f0', emoji: '🐙', title: 'GitHub' },
  'supabase':              { color: '#3ecf8e', emoji: '⚡', title: 'Supabase' },
  'playwright':            { color: '#45ba4b', emoji: '🎭', title: 'Playwright' },
  'chrome':                { color: '#4285f4', emoji: '🌐', title: 'Chrome' },
  'memory':                { color: '#ff9800', emoji: '🧠', title: 'Memory' },
  'seo':                   { color: '#4caf50', emoji: '📊', title: 'SEO' },
  'gmail':                 { color: '#ea4335', emoji: '📧', title: 'Gmail' },
  'ios-simulator':         { color: '#a2aaad', emoji: '📱', title: 'iOS' },
  'assistant':             { color: '#cc785c', emoji: '🤖', title: 'Claude' },
    'default':              { color: '#95a5a6', emoji: '👤', title: 'Worker' },
}

/**
 * The business team's roles, as the office draws them (docs/hermes-office/AGENTS.md).
 *
 * A business agent sends the same `agent_spawned` event a dev agent does; this
 * table is the only difference between them. `role` must be the key exactly —
 * a role missing here draws nothing at all, with no error anywhere.
 *
 * `desk` is a spot id in src/rooms.ts (docs/hermes-office/ROOMS.md holds the
 * map), never a dev spot: the two teams share the building, not the desks.
 */
export interface BusinessAgentConfig {
  color: string
  emoji: string
  desk: string
  room: RoomId
}

/** Business roles that fit any company (docs/hermes-office/AGENTS.md §4.1) */
export const GENERIC_BIZ_CONFIGS = {
  Orchestrator: { color: '#8b5cf6', emoji: '🧠', desk: 'biz-b1', room: 'business-suite' },
  Sales:        { color: '#f59e0b', emoji: '💼', desk: 'biz-b2', room: 'business-suite' },
  Marketing:    { color: '#ec4899', emoji: '📣', desk: 'biz-b3', room: 'business-suite' },
  Ops:          { color: '#6366f1', emoji: '⚙️', desk: 'biz-b4', room: 'business-suite' },
  Support:      { color: '#10b981', emoji: '🎧', desk: 'biz-m1', room: 'main-office' },
} as const satisfies Record<string, BusinessAgentConfig>

/** AniWatch's own roles, 26 of them (docs/hermes-office/AGENTS.md §4.2–§4.6) */
export const ANIWATCH_AGENT_CONFIGS = {
  // Core Ops — server room, 24/7
  Scraper:          { color: '#64748b', emoji: '🕷️', desk: 'biz-s1', room: 'server-room' },
  Metadata:         { color: '#0ea5e9', emoji: '📋', desk: 'biz-s2', room: 'server-room' },
  Encoder:          { color: '#f97316', emoji: '🔄', desk: 'biz-s3', room: 'server-room' },
  Subtitle:         { color: '#38bdf8', emoji: '🌐', desk: 'biz-s4', room: 'server-room' },
  TranslationAgent: { color: '#34d399', emoji: '🌏', desk: 'biz-s5', room: 'server-room' },
  QualityChecker:   { color: '#84cc16', emoji: '🔍', desk: 'biz-s6', room: 'server-room' },
  EpisodeScheduler: { color: '#60a5fa', emoji: '📅', desk: 'biz-s7', room: 'server-room' },
  Notifier:         { color: '#facc15', emoji: '🔔', desk: 'biz-s8', room: 'server-room' },
  CacheWarmer:      { color: '#a78bfa', emoji: '⚡', desk: 'biz-s9', room: 'server-room' },
  Resolver:         { color: '#22d3ee', emoji: '🔗', desk: 'biz-s10', room: 'server-room' },

  // Community — main office, beside the dev desks
  Moderator:        { color: '#f43f5e', emoji: '🛡️', desk: 'biz-m2', room: 'main-office' },
  UserReportAgent:  { color: '#fb923c', emoji: '🚨', desk: 'biz-m3', room: 'main-office' },

  // Growth — creative studio
  Analytics:        { color: '#06b6d4', emoji: '📊', desk: 'biz-c1', room: 'creative-studio' },
  SEO:              { color: '#4ade80', emoji: '🔎', desk: 'biz-c2', room: 'creative-studio' },
  SocialMedia:      { color: '#fb7185', emoji: '📱', desk: 'biz-c3', room: 'creative-studio' },
  Recommendation:   { color: '#c084fc', emoji: '🎯', desk: 'biz-c4', room: 'creative-studio' },
  Retention:        { color: '#f472b6', emoji: '💌', desk: 'biz-c5', room: 'creative-studio' },

  // Premium pipeline — creative studio
  DesignAgent:      { color: '#e879f9', emoji: '🎨', desk: 'biz-c6', room: 'creative-studio' },
  QAAgent:          { color: '#a3e635', emoji: '✅', desk: 'biz-c7', room: 'creative-studio' },
  PricingAgent:     { color: '#fbbf24', emoji: '💰', desk: 'biz-c8', room: 'creative-studio' },
  PreviewAgent:     { color: '#7dd3fc', emoji: '👁️', desk: 'biz-c9', room: 'creative-studio' },
  Publisher:        { color: '#34d399', emoji: '🚀', desk: 'biz-c10', room: 'creative-studio' },

  // Finance / Legal / Security — finance & legal
  RevenueTracker:   { color: '#4ade80', emoji: '💵', desk: 'biz-f1', room: 'finance-legal' },
  PaymentAgent:     { color: '#34d399', emoji: '💳', desk: 'biz-f2', room: 'finance-legal' },
  DMCA:             { color: '#fca5a5', emoji: '⚖️', desk: 'biz-f3', room: 'finance-legal' },
  SecOps:           { color: '#94a3b8', emoji: '🔐', desk: 'biz-f4', room: 'finance-legal' },
} as const satisfies Record<string, BusinessAgentConfig>

/** All 31 business roles, the key set every `agent_start` role must match */
export const BUSINESS_AGENT_CONFIGS = {
  ...GENERIC_BIZ_CONFIGS,
  ...ANIWATCH_AGENT_CONFIGS,
} as const

export type BusinessRole = keyof typeof BUSINESS_AGENT_CONFIGS

/** True when `role` is a business role (so the office seats it by this table, not as a dev agent) */
export function isBusinessRole(role: string): role is BusinessRole {
  return Object.prototype.hasOwnProperty.call(BUSINESS_AGENT_CONFIGS, role)
}
