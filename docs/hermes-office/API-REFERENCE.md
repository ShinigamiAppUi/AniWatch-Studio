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
| `agent_waiting` | minta approval (bisnis) | `agentId`, `message`, `options[]` |
| `agent_approval_done` | jawaban sudah diterima / timeout | `agentId` |
| — | gagal | `agent_working` dengan `failed: true` (tidak ada tipe `agent_error`) |
| `biz_metric_update` | metric berubah | `metrics` (bentuk §2) |
| `chat_message`, `permission_request`, `signal`, … | base | lihat `docs/reference.md` |

### Client → server

| `type` | Body | Efek |
| --- | --- | --- |
| `approval_response` | `{agentId, decision}` | diteruskan `biz-events.js` → sidecar |
| lainnya | base | tidak berubah |

**Istilah:** `agent_waiting(...)` adalah fungsi bridge **dan** tipe event-nya. `agent_error(...)`
hanya nama fungsi: di kabel ia `agent_working` + `failed: true`, karena base tidak punya tipe
`agent_error`.

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

#### `agent_waiting` — tangan naik ✋ dan kartu tombol

```json
{
  "type": "agent_waiting",
  "agentId": "paymentagent-9f8e7d",
  "message": "Refund Rp 149.000 dari user 42, dibeli 3 hari lalu",
  "options": ["Approve Refund", "Tolak", "Minta Info Lebih"]
}
```

**Efek visual:** karakter menampilkan bubble `✋ <message>`, dan panel chat menampilkan satu kartu
(`src/components/BizApprovalCards.tsx`, state di `src/bizApproval.ts`) dengan satu tombol per
`options` — maksimal 6 label, 80 karakter masing-masing.

**Jawaban:** tombol mengirim `approval_response` lewat WS. Server meneruskannya ke sidecar
(`POST /approval-callback`) **hanya dari socket `trusted`**; halaman read-only tetap melihat kartu
tapi tanpa tombol. Agent mengambil jawaban lewat `wait_for_approval()`.

**Kartu hilang** saat bridge mengirim `agent_approval_done` (jawaban diterima atau timeout) atau saat
agent selesai (`agent_completed`). Kartu **tidak** disimpan server: reload halaman menghapus kartu
yang masih terbuka — agent tetap menunggu sampai timeout.

**Dipanggil oleh:** `bridge.agent_waiting()` — **sebelum** `wait_for_approval()`, tidak pernah
sesudahnya.

#### `biz_metric_update` — panel metrics bergerak

```json
{ "type": "biz_metric_update", "metrics": { "today": { "leads_qualified": 12 }, "sla": { "breach_count": 1 }, "agents_active": ["Support"], "last_updated": "2026-11-16T09:41:00.000Z" } }
```

**Efek visual:** angka di `BizMetricsPanel` (tombol **biz**) berubah; baris **SLA breaches** dan
**Chargebacks** berwarna merah kalau nilainya bukan 0. Bukan animasi karakter.

**Dipanggil oleh:** `POST /biz-metrics` (server yang membroadcast, bukan bridge).

---

## 4. FastAPI sidecar (8765)

**Sudah ada di kode** (`webhook_server/main.py`, `approval.py`): `GET /health`,
`GET /approval/{agent_id}` (one-shot `pop`), `POST /approval-callback` (`{agentId, decision}` → 400
kalau kosong). `/webhook` dan `/webhook/payment` ada sejak W4 (`triggers.py`, `payments.py`).

### `POST /webhook` (W4)

Header wajib `X-Webhook-Secret`. Body:

```json
{ "type": "new_lead", "data": { "name": "Budi", "email": "budi@example.com" }, "source": "typeform" }
```

`new_lead`, `form_submit`, dan `deal_stage_change` menjalankan agent Sales (W8 sisa), bukan hanya
menggambar karakter. Field yang dibaca `qualify_lead`: `name`, `email`, `company`, `company_size`,
`plan`, `budget_idr`, `source`. `deal_stage_change` butuh `lead_id` (atau `id`/`email`) + `stage`
(`new`/`contacted`/`qualified`/`meeting`/`won`/`lost`, alias `closed_won`, `demo`); `meeting` juga
butuh `when` + `timezone`. Respons route tetap `{"status":"queued"}` — hasil kerjanya terbaca di
`/leads`, bubble karakter, dan SharedContext.

`type` harus salah satu `SUPPORTED_TRIGGERS` (kalau tidak → 400):

`new_lead`, `form_submit`, `deal_stage_change`, `analytics_ready`, `content_schedule`,
`support_ticket`, `new_email`, `episode_released`, `weekly_analytics`, `announce_episode`,
`retention_check`, `chargeback_received`, `user_report`.

Selalu dijawab `{"status":"queued"}` setelah trigger diserahkan ke worker thread
(`triggers.run_trigger`: Orchestrator muncul lebih dulu, lalu role tujuannya) — semua trigger lewat
Orchestrator (fix Rev 3 #4). Type yang tidak terpetakan → 400, **tidak pernah** dialihkan ke `ops`.
Sidecar menolak start kalau `WEBHOOK_SECRET` kosong.

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

### `POST /command` (W7)

Pintu slash command bisnis dari chat panel. Body `{"text": "/design border neon"}`; jawaban
`{handled, ok, reply}`. Hanya loopback, tanpa secret sendiri — sama seperti `/approval-callback`,
keamanannya adalah binding loopback (SECURITY.md §4.2). `handled: false` berarti baris itu bukan
command bisnis dan tetap menjadi pesan chat biasa.

`/design` menjawab segera (item sudah `pending_approval`); kartu approval-nya diangkat worker thread
(`premium.request_approval`) karena `char.ask` menunggu tombol. Tiga command yang dilayani:

| Command | Efek |
| --- | --- |
| `/design [kind] [tema]` | buat item + design/QA/harga/preview, lalu antrikan kartu approval |
| `/pending-items` | daftar `status='pending_approval'`, maks 6 baris |
| `/approve [id]` | `premium.decide('Approve')` — penulis status yang sama dengan tombol kartu |

`server/biz-events.js` yang merelai: `bizSlashCommand()` mengirim baris yang cocok ke sini dan
mengembalikan `reply`-nya ke chat; sidecar mati → jawaban menyebut command yang tidak dijalankan.

```bash
curl -s -X POST http://127.0.0.1:8765/command \
  -H 'Content-Type: application/json' -d '{"text":"/pending-items"}'
# → {"handled":true,"ok":true,"reply":"🗂 1 item menunggu approval:\n- pm-1a2b border/neon ..."}
```

### `POST /webhook/payment` (W4 verifikasi → W9 PaymentAgent)

Notifikasi Midtrans. Header `X-Signature-Key` harus sama dengan
`sha512(order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY)` (explicit `utf-8`,
`.get('', ...)` default — fix Rev 3 #9). Urutannya: verifikasi → `record()` (satu baris per
notifikasi, `INSERT OR IGNORE`) → **PaymentAgent** (`finance.handle_payment_webhook`) → handoff-nya
diikuti (`payment_settled` → RevenueTracker, `chargeback` → SecOps).

Jawaban selalu `{"status":"queued","action":...}`; `action` adalah yang benar-benar terjadi
(`settled`, `grace`, `downgrade`, `chargeback`, `refunded`, `ignored`, `duplicate`).

`transaction_status: "refund_request"` bukan status Midtrans: itu cara refund **diminta** lewat pintu
yang sama, sehingga permintaan ikut terverifikasi signature. Hanya status ini yang memblokir (kartu
Approve/Tolak/Minta Info, timeout 24 jam), jadi ia diangkat di worker thread dan jawabannya
`{"status":"queued","action":"refund_requested"}`.

```bash
# settlement: satu baris, satu langganan, satu snapshot revenue
curl -s -X POST http://127.0.0.1:8765/webhook/payment \
  -H 'Content-Type: application/json' -H "X-Signature-Key: $SIG" \
  -d '{"order_id":"o-9","status_code":"200","gross_amount":"99000.00",
       "transaction_status":"settlement","customer_id":"budi@example.com"}'
# → {"status":"queued","action":"settled"}
```

### `GET /health`

`{"status":"ok","pending_approvals":n,"jobs":[{id,next_run_time}],"pending_jobs":[{id,reason}],"mail":{...}}`.
Tidak menyentuh office. `pending_approvals` menghitung **keputusan yang belum diambil**, bukan kartu
yang sedang terbuka: sidecar baru tahu tentang kartu saat tombolnya ditekan. `jobs` kosong kalau
scheduler belum jalan (mis. app di-import tanpa lifespan), dan `pending_jobs` adalah job
SCHEDULER.md yang menunggu agent W6–W9.

`mail` adalah kanal keluar Support: `{"configured": bool, "last": {at, to, sent, error} | null}`.
`configured` false berarti `SMTP_HOST` kosong, jadi setiap balasan Support **gagal** dengan alasan
`SMTP belum dikonfigurasi` dan tiketnya tetap `open` (ENV-VARS.md §3b). `last` adalah percobaan
terakhir, berhasil atau tidak — cara tercepat menjawab "kenapa tiket itu tidak dibalas".

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

Mengirim `agent_waiting` (`message` + `options`), jadi karakter menaikkan tangan ✋ dan kartu
tombol muncul di panel chat. `options` wajib 1–6 label; labelnya yang dikembalikan
`wait_for_approval`. **Wajib dipanggil sebelum** `wait_for_approval` — kalau dibalik, agent polling
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

Didaftarkan di chat routing yang sama. Format: `<command> [arg]`. **Sudah hidup (W7–W11d, 26
command):** W7 — `/design`, `/pending-items`, `/approve`; W9 — `/revenue`, `/payments`,
`/subscriptions`, `/refunds`, `/chargeback`, `/security`, `/takedown`; W10 — sisanya di dua tabel
bawah; W11d — `/scrape`, `/resolver`, `/sources`. Base command di `server/index.js` menang lebih dulu, lalu baris yang cocok direlai
`bizSlashCommand()` ke sidecar `POST /command`. `BIZ_SLASH_COMMANDS` (`server/biz-events.js`) dan
`COMMANDS` (`webhook_server/commands.py`) memuat daftar yang sama; `tests/biz-commands.test.ts` dan
selfcheck W10 memeriksanya.

| Command W9 | Output | Sumber data |
| --- | --- | --- |
| `/revenue` | 24 jam + 7 hari, antrean refund, anomali, path snapshot | `payment_events` → `media/published/revenue/` |
| `/payments` | notifikasi 24 jam per status | `payment_events` |
| `/subscriptions` | jumlah plan, grace, kedaluwarsa | `subscription_status` |
| `/refunds` | refund `pending` (menunggu kartu) | `payment_events` `refund_request` |
| `/chargeback` | chargeback terbaru | `payment_events` status `chargeback` |
| `/security` | insiden 24 jam + status feed + chargeback per akun | `security_incidents`, `payment_events` |
| `/takedown [episode_id] [alasan]` | verifikasi + catat + handoff ke EpisodeScheduler | `dmca_requests`, `episode_schedule` |

| Command W10 | Output | Sumber data |
| --- | --- | --- |
| `/biz` | counter hari ini, SLA, siapa yang bekerja, dan jumlah surat selamat datang yang menyerah. **Butuh kantor berjalan**: tanpa `GET /biz-metrics` jawabannya alasan, bukan angka (baris campaign tetap muncul) | `GET /biz-metrics` (`chat.db`), `campaign:*` di DB sidecar |
| `/leads` | pipeline per stage (**semua** `lead:*`, bukan hanya hari ini) + jumlah lead masuk hari ini + handoff ber-subject `lead:` yang belum diambil, dikelompokkan per rute `Sales→Marketing` + lead yang surat selamat datangnya sudah menyerah. Tanpa lead: hari itu memang kosong | SharedContext `lead:*`, `handoff.pending()`, `campaign:*` (ditulis agent Sales/Marketing) |
| `/tickets` | jumlah per status + 3 tiket terbuka terbaru | `tickets` |
| `/sla` | compliance tiket selesai (7 hari), yang lewat deadline, rata-rata respons pertama + jumlah sampel | `tickets` |
| `/topselling` | jumlah item live/dicabut. **Tidak ada ranking**: penjualan per item tidak tercatat | `premium_items`, `payment_events` |
| `/incidents` | 10 baris `security_incidents` terakhir | `security_incidents` |
| `/unban <ip\|user>` | baris `unban` baru, bukan delete | `security_incidents` |
| `/schedule` | antrean embargo + tiga yang publish berikutnya | `episode_schedule` |
| `/embargo [episode_id]` | detail satu schedule, atau daftar yang menunggu | `episode_schedule` |
| `/translations` | track per status + episode yang perlu review | `subtitle_tracks` |
| `/approve-sub <episode_id>` | `needs_review` → `approved`; tanpa id → daftar episode | `subtitle_tracks` |
| `/reports` | laporan user hari ini per status dan kategori | `user_reports` |
| `/report-stats` | tren 7 hari per hari + per kategori | `user_reports` |

| Command W11d | Output | Sumber data |
| --- | --- | --- |
| `/scrape [source\|episode]` | antrean `queued/claimed/done/gave_up`, baris give-up terakhir, filter per item bila backend mengirimnya | `GET /v1/admin/scrape/queue` |
| `/resolver` | sumber mati/degraded, host tanpa adapter, `gave_up`, `need_direct` tertunda; menyegarkan maksimal tiga halaman (dry run) | `GET /v1/admin/sources/health`, `GET /v1/admin/scrape/queue`, `POST /v1/admin/media/resolve` |
| `/sources` | jumlah `active`/`degraded`/`dead`/`unverified` per content type + sumber gagal berulang | `GET /v1/admin/sources/health` |

Ketiganya membaca `ANIWATCH_API_URL` + `ANIWATCH_ADMIN_TOKEN` (§ENV-VARS §3f). Tanpa keduanya
jawabannya `belum dikonfigurasi` + alasan, bukan angka nol yang terlihat seperti sistem sehat.

`/cancel-schedule [id]` dari rancangan lama **tidak** didaftarkan: pintunya `/takedown`, yang mencatat
audit DMCA sebelum membatalkan. Dua command untuk satu efek hanya membuat audit punya dua bentuk.
`/topselling` dan `/leads` adalah jawaban jujur tentang data yang belum ada, bukan laporan palsu:
kantor hanya menampilkan angka yang bisa diperiksa di DB.

Surat selamat datang yang sudah menyerah ikut ditampilkan: job `campaign_retry` berhenti setelah
`MAX_WELCOME_ATTEMPTS = 4` dan meninggalkan catatan `campaign:<lead>` dengan `sent: false` +
`last_error`. `/leads` menambahkan satu baris `⚠️ Surat selamat datang menyerah (N): <lead>` (dan
field `campaigns_gave_up`), `/biz` menambahkan baris yang sama beserta `campaigns_gave_up`. Baris itu
dibaca dari DB sidecar sendiri, jadi tetap muncul ketika kantor mati — kegagalan kirim tidak
menunggu panel hidup untuk terlihat.

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
