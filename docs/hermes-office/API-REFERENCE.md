# Hermes Office — API Reference

Nov 16, 2026 · @Shin · Sumber tunggal untuk endpoint, event WebSocket, dan slash command.

Tiga permukaan API:

| Permukaan | Port | Auth | Dipakai oleh |
| --- | --- | --- | --- |
| Express REST + WebSocket | 3334 | Bearer token / token UI | bridge, UI, slash command |
| FastAPI sidecar | 8765 | secret header / signature | webhook luar, Midtrans, bridge polling |
| Chat routing | 3334 | — (loopback) | manusia di chat panel |

---

## 1. Express — endpoint base (tidak diubah)

Terverifikasi ada di `server/index.js`. Kolom Auth: **T** = Bearer token, **UI** = token UI
(`#token=` di URL), **—** = loopback terbuka (read-only).

| Method | Path | Auth | Fungsi |
| --- | --- | --- | --- |
| GET | `/health` | — | status server + pipeline hooks |
| GET | `/config` | — | config boss (`office.config.json`) |
| GET | `/roster` | — | daftar agent yang dikenal |
| POST | `/event` | T | **pintu tunggal semua event** (dev & bisnis) |
| GET | `/agents` | — | snapshot semua agent |
| GET | `/agents/:id` | — | satu agent + transkrip |
| GET | `/sessions` | — | session Claude Code aktif |
| GET | `/signals` | — | event deploy/build/test/push |
| GET | `/recap` | — | rekap harian |
| GET | `/settings` | — | settings kantor |
| POST | `/settings` | UI | ubah settings |
| POST | `/chat` | UI | kirim pesan chat |
| GET | `/chat` | — | riwayat chat |
| POST | `/chat/reply` | T | balasan Claude untuk chat |
| POST | `/chat/inbox/read` | T | tandai inbox agent terbaca |
| POST | `/chat/seen` | T | tandai pesan terlihat |
| POST | `/chat/react` | T | reaksi emoji |
| POST | `/chat/typing` | — | indikator mengetik |
| GET/POST | `/chat/cron-state` | — | state cron chat |
| POST | `/a2a` | T | pesan agent-to-agent |
| GET | `/a2a/agents` | — | katalog agent A2A |

`POST /event` menolak tipe yang tidak dikenal (400). Tipe yang sah ada di
`KNOWN_EVENT_TYPES` (`server/index.js`): `agent_spawned`, `agent_working`, `agent_completed`,
`agent_linked`, `agent_started`, `mcp_call`, `mcp_done`, `session_started`, `session_ended`,
`session_prompt`, `session_turn_end`, `session_needs_you`, `session_tool_done`, `session_error`,
`session_compact`, `session_cwd`, `session_model`, `signal`, `task_created`, `task_completed`,
`session_elicitation_done`, `teammate_idle`. **Tidak ada tipe baru** untuk bisnis — itu memang
tujuannya.

---

## 2. Express — endpoint bisnis (baru)

### `POST /biz-metrics`

Auth: Bearer. Body: `{ "delta": { "<key>": <int>, ... } }`. Delta untuk counter, nilai absolut
untuk gauge (`GAUGE_KEYS`).

```bash
TOKEN=$(cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token")
curl -s -X POST http://127.0.0.1:3334/biz-metrics \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"delta":{"leads_qualified":1,"emails_sent":2}}'
# → {"ok":true}
```

Server: upsert `biz_metrics` (DB-SCHEMA.md §2) → `broadcast({type:'biz_metric_update', metrics})`.

### `GET /biz-metrics`

Auth: —. Bentuk respons (dibaca `BizMetricsPanel`, sama untuk semua client):

```json
{
  "today": {
    "leads_qualified": 4,
    "emails_sent": 11,
    "tickets_resolved": 7,
    "tickets_pending": 2,
    "crm_updates": 3,
    "refunds_processed": 0,
    "chargebacks": 0
  },
  "sla": { "avg_response_min": 23, "breach_count": 1 },
  "agents_active": ["Support", "Scraper"],
  "last_updated": "2026-11-16T09:41:00.000Z"
}
```

`agents_active` dihitung dari snapshot agent (state `working`), bukan disimpan di DB.

### `server/biz-events.js` (ESM — fix Rev 3.1 #1)

```js
// server/biz-events.js
const SIDECAR_URL = process.env.SIDECAR_URL || 'http://127.0.0.1:8765'

const GAUGE_KEYS = new Set([
  'tickets_pending', 'sla_avg_response_min', 'sla_breach_count',
])

const dayKey = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function registerBizRoutes(app, db, broadcast) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS biz_metrics (
      key TEXT NOT NULL, day TEXT NOT NULL,
      value INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
      PRIMARY KEY (key, day)
    );
    CREATE INDEX IF NOT EXISTS idx_biz_metrics_day ON biz_metrics (day);
  `)

  const upsertDelta = db.prepare(`
    INSERT INTO biz_metrics (key, day, value, updated_at) VALUES (?, ?, ?, ?)
    ON CONFLICT(key, day) DO UPDATE SET
      value = value + excluded.value, updated_at = excluded.updated_at
  `)
  const upsertGauge = db.prepare(`
    INSERT INTO biz_metrics (key, day, value, updated_at) VALUES (?, ?, ?, ?)
    ON CONFLICT(key, day) DO UPDATE SET
      value = excluded.value, updated_at = excluded.updated_at
  `)

  app.post('/biz-metrics', (req, res) => {
    const { delta } = req.body || {}
    if (!delta || typeof delta !== 'object' || Array.isArray(delta)) {
      return res.status(400).json({ error: 'delta wajib berupa object' })
    }
    const now = Date.now(), day = dayKey()
    const write = db.transaction((entries) => {
      for (const [key, raw] of entries) {
        const val = Number(raw)
        if (!Number.isFinite(val)) continue          // abaikan key sampah, jangan crash
        ;(GAUGE_KEYS.has(key) ? upsertGauge : upsertDelta).run(key, day, Math.trunc(val), now)
      }
    })
    write(Object.entries(delta))

    const metrics = getBizMetrics(db)
    broadcast({ type: 'biz_metric_update', metrics })
    res.json({ ok: true })
  })

  app.get('/biz-metrics', (_req, res) => res.json(getBizMetrics(db)))
}

export async function handleBizWsMessage(_ws, data) {
  if (data?.type !== 'approval_response' || !data.agentId) return false
  try {
    await fetch(`${SIDECAR_URL}/approval-callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agentId: data.agentId, decision: data.decision }),
    })
  } catch (err) {
    console.warn('[biz-events] sidecar tidak bisa dihubungi:', err.message)
  }
  return true
}

function getBizMetrics(db) {
  const day = dayKey()
  const rows = db.prepare('SELECT key, value FROM biz_metrics WHERE day = ?').all(day)
  const all = Object.fromEntries(rows.map(r => [r.key, r.value]))
  const agents = []   // diisi handler WS: agent ber-state 'working'
  return {
    today: {
      leads_qualified:  all.leads_qualified  ?? 0,
      emails_sent:      all.emails_sent      ?? 0,
      tickets_resolved: all.tickets_resolved ?? 0,
      tickets_pending:  all.tickets_pending  ?? 0,
      crm_updates:      all.crm_updates      ?? 0,
      refunds_processed:all.refunds_processed ?? 0,
      chargebacks:      all.chargebacks      ?? 0,
    },
    sla: {
      avg_response_min: all.sla_avg_response_min ?? 0,
      breach_count:     all.sla_breach_count     ?? 0,
    },
    agents_active: agents,
    last_updated: new Date().toISOString(),
  }
}
```

Disisipkan ke `server/index.js` (2 baris):

```js
import { registerBizRoutes, handleBizWsMessage } from './biz-events.js'
// ... setelah app & db & broadcast siap:
registerBizRoutes(app, db, broadcast, { requireToken, activeAgents })
// ... di dalam wss.on('connection', ws => ...), dengan `trusted` hasil handshake:
ws.on('message', data => { handleBizWsMessage(data, { trusted }) })
```

---

## 3. WebSocket (3334)

### Server → client

| `type` | Kapan | Payload penting |
| --- | --- | --- |
| `agent_spawned` | agent mulai | `agent: {id, name, role, task}` |
| `agent_working` | tool call | `agentId`, `status`, `tool`, `failed?` |
| `agent_completed` | selesai | `agentId`, `result` |
| — | gagal / minta approval | **tidak ada tipe baru**: keduanya `agent_working` dengan `failed: true` atau status `✋ …` (§3.1) |
| `biz_metric_update` | metric berubah | `metrics` (bentuk §2) |
| `chat_message`, `permission_request`, `signal`, … | base | lihat `docs/reference.md` |

### Client → server

| `type` | Body | Efek |
| --- | --- | --- |
| `approval_response` | `{agentId, decision}` | diteruskan `biz-events.js` → sidecar |
| lainnya | base | tidak berubah |

**Istilah:** `agent_error(...)` dan `agent_waiting(...)` adalah nama *fungsi bridge*
(`hermes_bridge/bridge.py`), bukan tipe event. Di kabel keduanya `agent_working`
(+`failed: true`, atau status `✋ …`), karena `KNOWN_EVENT_TYPES` base tidak berubah.

`approval_response` adalah **satu-satunya** pesan baru dari UI. Kalau sidecar mati, WS tetap
menerima pesan dan hanya menulis warning — UI tidak boleh menggantung.

### Payload dan efek visual

Bentuk payload sudah final; yang berubah hanya isinya. Semua dikirim `bridge` lewat `POST /event`,
lalu di-broadcast apa adanya ke UI.

#### `agent_spawned` — karakter masuk dan duduk

```json
{
  "type": "agent_spawned",
  "agent": {
    "id": "scraper-a1b2c3",
    "name": "Scraper",
    "role": "Scraper",
    "task": "Ambil episode baru dari source"
  }
}
```

**Efek visual:** karakter muncul dari pintu depan koridor, berjalan ke meja milik `role`
(ROOMS.md), lalu duduk. Kalau `role` tidak ada di `BUSINESS_AGENT_CONFIGS`, karakter **tidak muncul
sama sekali** — tidak ada error di UI, jadi periksa ejaan role dulu.

**Dipanggil oleh:** `bridge.agent_start()`.

#### `agent_working` — speech bubble bergerak

```json
{
  "type": "agent_working",
  "agentId": "scraper-a1b2c3",
  "status": "Mengambil halaman source...",
  "tool": "fetch_source"
}
```

**Efek visual:** bubble status berganti, karakter tetap bekerja. `failed: true` membuat bubble merah
sekilas (tool gagal) tanpa mengeluarkan karakter.

**Dipanggil oleh:** `bridge.agent_update()`, minimal sekali per tool call.

#### `agent_completed` — jempol lalu keluar

```json
{
  "type": "agent_completed",
  "agentId": "scraper-a1b2c3",
  "result": "3 episode baru tersimpan"
}
```

**Efek visual:** karakter 👍, berjalan ke pintu, keluar lewat koridor. Kursinya langsung bebas.

**Dipanggil oleh:** `bridge.agent_done()` — tepat sekali per `agent_start`.

#### gagal — `agent_working` dengan `failed: true`

```json
{
  "type": "agent_working",
  "agentId": "scraper-a1b2c3",
  "status": "Source timeout setelah 3 percobaan",
  "failed": true
}
```

**Efek visual:** bubble merah (❌). `retrying: true` → karakter **tetap** di meja; `false` → bridge
langsung mengirim `agent_completed` dengan hasil `berhenti: …`, jadi karakter keluar tanpa perayaan.

**Dipanggil oleh:** `bridge.agent_error()`. Base tidak punya tipe `agent_error`, dan fork ini tidak
menambahkannya.

#### tangan naik ✋ — juga `agent_working`

```json
{
  "type": "agent_working",
  "agentId": "payment-9f8e7d",
  "status": "✋ Refund Rp 149.000 dari user 42, dibeli 3 hari lalu"
}
```

**Efek visual (W2):** bubble status berisi ✋; tidak ada card di UI. Card dengan satu tombol per
`options` **belum dibangun** — itu bagian W10 (PLAN.md). Yang sudah berjalan: `wait_for_approval()`
mem-poll sidecar, dan `POST /approval-callback` (dipanggil `biz-events.js` saat kelak ada
`approval_response` dari UI) mengisi mailbox itu.

**Dipanggil oleh:** `bridge.agent_waiting()` — **sebelum** `wait_for_approval()`, tidak pernah
sesudahnya.

#### `biz_metric_update` — panel metrics bergerak

```json
{ "type": "biz_metric_update", "metrics": { "today": { "leads_qualified": 12 }, "sla": { "breach_count": 1 }, "agents_active": ["Support"], "last_updated": "2026-11-16T09:41:00.000Z" } }
```

**Efek visual:** angka di `BizMetricsPanel` berubah; baris SLA berkedip kalau `breach_count > 0`.
Bukan animasi karakter.

**Dipanggil oleh:** `POST /biz-metrics` (server yang membroadcast, bukan bridge).

---

## 4. FastAPI sidecar (8765)

**Sudah ada di W2** (`webhook_server/main.py`, `approval.py`): `GET /health`,
`GET /approval/{agent_id}` (one-shot `pop`), `POST /approval-callback` (`{agentId, decision}` → 400
kalau kosong). Tiga route di bawah ini **W3–W5**, belum ada di kode.

### `POST /webhook` (W4 — belum ada)

Header wajib `X-Webhook-Secret`. Body:

```json
{ "type": "new_lead", "data": { "name": "Budi", "email": "budi@example.com" }, "source": "typeform" }
```

`type` harus salah satu `SUPPORTED_TRIGGERS` (kalau tidak → 400):

`new_lead`, `form_submit`, `deal_stage_change`, `analytics_ready`, `content_schedule`,
`support_ticket`, `new_email`, `episode_released`, `weekly_analytics`, `announce_episode`,
`retention_check`, `chargeback_received`, `user_report`.

Selalu dijawab `{"status":"queued"}` setelah `asyncio.create_task(run_orchestrator_async(...))` —
semua trigger lewat Orchestrator (fix Rev 3 #4).

```bash
curl -s -X POST http://127.0.0.1:8765/webhook \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"type":"support_ticket","data":{"id":"t-1","subject":"video buffering"}}'
```

### `GET /approval/{agent_id}`

Dipakai `wait_for_approval` (poll 3 dtk). `{"decision": null}` selama belum ada, lalu
`{"decision": "Approve"}` **satu kali** (one-shot `pop`). Entri lebih tua dari 6 jam dibuang.

### `POST /approval-callback`

Body `{agentId, decision}`. Dipanggil `biz-events.js`. 400 kalau salah satu kosong.

### `POST /webhook/payment` (W5 — belum ada)

Notifikasi Midtrans. Header `X-Signature-Key` harus sama dengan
`sha512(order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY)` (explicit `utf-8`,
`.get('', ...)` default — fix Rev 3 #9). Sukses → `{"status":"queued"}` ke PaymentAgent.

### `GET /health`

`{"status":"ok","pending_approvals":n}`. Tidak menyentuh office.

---

## 5. Bridge — permukaan Python

Tujuh fungsi publik. Agent **hanya** memakai ini; `bridge._post` privat (Rev 3.1 #3).

```python
from hermes_bridge import bridge

aid = bridge.agent_start("Scraper", "Scraper", "Cek episode baru")
bridge.agent_update(aid, "Mengambil halaman source...", tool="fetch_source")
bridge.agent_waiting(aid, "Episode corrupt, coba source lain?", ["Coba", "Batalkan"])
decision = bridge.wait_for_approval(aid, timeout=300)
bridge.agent_done(aid, "Episode tersimpan ✓")
bridge.agent_error(aid, "Timeout source", retrying=False)
bridge.update_biz_metrics({"tickets_resolved": 1})
```

### `agent_start(name, role, task) -> str`

Memunculkan karakter dan mengembalikan id yang dipakai semua panggilan berikutnya.

| Arg | Arti |
| --- | --- |
| `name` | nama tampilan di bubble & inspector, bebas ("Scraper", "Quality Checker") |
| `role` | **key persis** di `BUSINESS_AGENT_CONFIGS` — menentukan warna, emoji, ruangan, meja |
| `task` | satu baris task untuk bubble awal |

**Returns:** `"{role.lower()}-{uuid6}"`, mis. `scraper-a1b2c3`.

```python
aid = bridge.agent_start("Translation Agent", "TranslationAgent", "Terjemahkan sub ep 12")
```

### `agent_update(agent_id, status, tool=None) -> None`

Update bubble. Panggil per tool call, bukan per baris log.

```python
bridge.agent_update(aid, "Menerjemahkan via DeepL...", tool="translate_text")
```

### `agent_waiting(agent_id, message, options) -> None`

Menaikkan tangan ✋ lewat bubble status (`agent_working`); `options` divalidasi dan disimpan bridge
untuk card di W10. **Wajib dipanggil sebelum** `wait_for_approval` — kalau dibalik, agent polling
untuk card yang belum pernah muncul (fix Rev 3 #1).

```python
bridge.agent_waiting(aid, "QA 0.62 di bawah 0.75. Lanjutkan?",
                     ["Approve & Lanjutkan", "Reject & Translate Ulang"])
```

### `wait_for_approval(agent_id, timeout=300) -> str`

Polling `GET {SIDECAR}/approval/{agent_id}` tiap 3 detik.

| Timeout | Dipakai untuk |
| --- | --- |
| 300 dtk (default) | keputusan biasa |
| 120 dtk | SLA breach (mendesak) |
| 3600 dtk | review terjemahan |
| 86400 dtk | refund (keputusan uang) |

**Returns:** isi `decision` persis seperti label tombol (mis. `"Approve Refund"`), atau `"timeout"`.
Timeout **bukan** exception: agent yang memutuskan apa artinya (biasanya `agent_error` + antrian
manusia).

```python
decision = bridge.wait_for_approval(aid, timeout=3600)
if decision == "timeout":
    bridge.agent_error(aid, "Tidak ada review dalam 1 jam", retrying=False)
    return "rejected"
```

### `agent_done(agent_id, result="done") -> None`

Karakter 👍 lalu keluar. Sekali per agent.

```python
bridge.agent_done(aid, "3 episode baru tersimpan ✓")
```

### `agent_error(agent_id, error, retrying=False) -> None`

`retrying=True` → karakter tetap di meja; `False` → selesai tanpa perayaan.

```python
bridge.agent_error(aid, "Source timeout", retrying=True)
```

### `update_biz_metrics(delta) -> None`

POST langsung ke `/biz-metrics` (bukan `/event`, fix Rev 3 #2). Counter dijumlahkan; key gauge
(`tickets_pending`, `sla_avg_response_min`, `sla_breach_count`) **mengganti** nilai.

```python
bridge.update_biz_metrics({"tickets_resolved": 1})
bridge.update_biz_metrics({"tickets_pending": 4})        # gauge — bukan +1
```


---

## 6. Slash command

### Base (tidak berubah)

`/status`, `/agents`, `/recap`, `/incident`, `/all-clear`, `/the-office`, `/clear`, `/help`.
Ditangani di `server/index.js` sebelum event diproses.

### Bisnis (baru)

Didaftarkan di chat routing yang sama. Format: `<command> [arg]`.

| Command | Output | Sumber data |
| --- | --- | --- |
| `/biz` | ringkasan bisnis hari ini | `GET /biz-metrics` |
| `/leads` | lead yang diproses hari ini | `shared_context` key `lead:*` |
| `/tickets` | tiket terbuka | `tickets` |
| `/sla` | compliance + yang lewat deadline | `tickets.sla_deadline` |
| `/revenue` | pemasukan hari ini + minggu ini | `payment_events`, `biz_metrics` |
| `/topselling` | item premium terlaris | `premium_items` + penjualan |
| `/payments` | ringkasan payment hari ini | `payment_events` |
| `/subscriptions` | subscription aktif + grace period | `subscription_status` |
| `/refunds` | refund menunggu approval | `payment_events` status pending |
| `/chargeback` | log chargeback terbaru | `payment_events` |
| `/security` | ancaman 24 jam | log SecOps |
| `/incidents` | insiden + aksi | log incident |
| `/unban [ip/user]` | manual unban | SecOps rule store |
| `/design [type] [tema]` | trigger Design Agent | Orchestrator |
| `/pending-items` | desain menunggu approval | `premium_items` |
| `/approve [id]` | approve item | `premium_items` → Publisher |
| `/schedule` | antrian + estimasi live | `episode_schedule` |
| `/embargo [episode_id]` | detail embargo | `episode_schedule` |
| `/cancel-schedule [id]` | batalkan schedule | `episode_schedule` |
| `/translations` | status terjemahan | `subtitle_tracks` |
| `/approve-sub [episode_id]` | approve subtitle | `subtitle_tracks` |
| `/reports` | laporan user hari ini | `user_reports` |
| `/report-stats` | tren 7 hari | `user_reports` |

Aturan respons: **satu pesan chat, maksimal 6 baris.** Command yang butuh daftar panjang
mengirim ringkasan + "…dan N lainnya" (chat panel bukan dashboard). Detail lengkap tetap di
`BizMetricsPanel`.

---

## 7. Kode error

| Kode | Endpoint | Arti | Tindakan |
| --- | --- | --- | --- |
| 400 | `/event` | tipe event tidak dikenal | periksa string `type` |
| 400 | `/webhook` | trigger tidak ada di `SUPPORTED_TRIGGERS` | tambah di **dua** tempat |
| 400 | `/biz-metrics` | `delta` bukan object | kirim `{delta:{...}}` |
| 401 | `/event`, `/biz-metrics` | token salah / server di-restart | ambil ulang `auth-token` |
| 403 | `/webhook` | secret salah | samakan `WEBHOOK_SECRET` |
| 403 | `/webhook/payment` | signature salah | cek urutan concat SHA-512 |
| 404 | `/approval/{id}` | agent id tidak dikenal | pastikan `agent_waiting` terkirim |
| 503 | `/health` | sidecar belum siap | tunggu startup / cek log |

Bridge tidak pernah melempar error HTTP ke agent: semua kegagalan jadi `agent_error` atau masuk DLQ.
