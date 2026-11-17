# Hermes Office — DB Schema

Nov 16, 2026 · @Shin · Sumber tunggal untuk semua tabel. Agent tidak menulis DDL; cukup menyebut
nama tabel.

Dua database, dua pemilik:

| DB | File | Pemilik | Isi |
| --- | --- | --- | --- |
| DB kantor | `~/.agent-office/chat.db` (`$AGENT_OFFICE_HOME`) | Express base | chat, stats harian |
| DB bisnis | `~/.hermes-office/hermes.db` | `hermes_bridge/db.py` | semua tabel bisnis |
| DLQ | `~/.hermes-office/dlq.db` | `hermes_bridge/queue.py` | antrian event gagal |
| Shared context | `~/.hermes-office/shared.db` | `hermes_bridge/shared_context.py` | context antar agent |
| KB | `~/.hermes-office/kb.db` | `hermes_bridge/kb/sqlite_kb.py` | artikel knowledge base |

Empat file untuk sisi bisnis dipisah karena umur datanya beda: DLQ dan context boleh dihapus kapan
saja tanpa kehilangan data bisnis. Semua dibuat di direktori mode `0700`, file `0600` (sama seperti
`chat.db` base).

---

## 1. DB kantor (jangan diubah)

Dibuat oleh base, **tidak boleh** dimigrasi di fork ini:

| Tabel | Isi |
| --- | --- |
| `messages` | chat panel (sender, role, text, timestamp, reactions, thread, seen, recipient, msg_type, read_at) |
| `daily_stats` | rekap harian `/recap` |
| `daily_seen` | penanda "sudah dilihat" untuk rekap |
| `daily_session_cost` | biaya per session per hari (meters payroll) |

Satu-satunya tambahan di DB kantor: tabel **`biz_metrics`** (§2), karena ia harus ikut satu koneksi
dengan `broadcast` server. Semua tabel lain milik bridge.

---

## 2. `biz_metrics` — DB kantor

Dibuat oleh `server/biz-events.js` saat startup (ESM). Satu baris per (key, hari), supaya panel bisa
menampilkan "hari ini" dan reset alami tanpa job tengah malam.

```sql
CREATE TABLE IF NOT EXISTS biz_metrics (
    key        TEXT    NOT NULL,
    day        TEXT    NOT NULL,              -- 'YYYY-MM-DD' lokal
    value      INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (key, day)
);

CREATE INDEX IF NOT EXISTS idx_biz_metrics_day ON biz_metrics (day);
```

Upsert dari `POST /biz-metrics`:

```sql
INSERT INTO biz_metrics (key, day, value, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(key, day) DO UPDATE SET
  value      = value + excluded.value,
  updated_at = excluded.updated_at;
```

**Writer:** `server/biz-events.js` (`POST /biz-metrics`) — dipanggil `bridge.update_biz_metrics()`
untuk counter, agent untuk gauge. · **Reader:** `GET /biz-metrics` (panel + `/biz`), dan broadcast
`biz_metric_update`.
**Umur data:** satu baris per (key, hari). Tidak ada job reset — hari baru berarti baris baru,
sehingga "hari ini" selalu benar tanpa menghapus apa pun.

Key yang dipakai panel (`GET /biz-metrics` mengembalikan bentuk ini):

| Key | Arti | Dikirim oleh |
| --- | --- | --- |
| `leads_qualified` | lead lolos kualifikasi | Sales |
| `emails_sent` | email terkirim | Sales, Marketing, Retention |
| `crm_updates` | update CRM | Sales |
| `tickets_resolved` | tiket selesai | Support |
| `tickets_pending` | tiket terbuka (gauge, bukan delta) | Support |
| `sla_avg_response_min` | rata-rata respons (gauge) | Support |
| `sla_breach_count` | tiket lewat SLA | Support |
| `refunds_processed` | refund disetujui | PaymentAgent |
| `subscriptions_lost` | downgrade karena gagal bayar | PaymentAgent |
| `chargebacks` | chargeback diterima | PaymentAgent |

Gauge (`*_pending`, `*_avg_*`, `*_breach_count`) dikirim sebagai **nilai absolut** dan ditulis
dengan `SET value = excluded.value`, bukan ditambah. Delta vs gauge dibedakan di `biz-events.js`
lewat daftar `GAUGE_KEYS`; jangan campur di satu payload.

---

## 3. `tickets` — Support

```sql
CREATE TABLE IF NOT EXISTS tickets (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    subject      TEXT NOT NULL,
    body         TEXT,
    channel      TEXT DEFAULT 'email',      -- email | form | chat
    priority     TEXT DEFAULT 'normal',     -- low | normal | high | urgent
    status       TEXT DEFAULT 'open',       -- open | pending | resolved | escalated
    received_at  REAL NOT NULL,
    sla_deadline REAL NOT NULL,
    resolved_at  REAL,
    assignee     TEXT,
    kb_article_id TEXT,
    updated_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_tickets_sla ON tickets (status, sla_deadline);
```

**Writer:** `SupportAgent.triage_ticket()` (baris baru), `check_sla_breaches()` (extend deadline /
resolve), `SupportAgent.resolve()`. · **Reader:** `check_sla_breaches`, `/tickets`, `/sla`, gauge
`tickets_pending` / `sla_*`.

Alur status: `open → pending → resolved | escalated`. `escalated` wajib punya `assignee`; tiket
`resolved` wajib punya `resolved_at`.

Query yang dipakai `check_sla_breaches`: `status IN ('open','pending') AND sla_deadline < now`.

---

## 4. `user_reports` — UserReportAgent

```sql
CREATE TABLE IF NOT EXISTS user_reports (
    id          TEXT PRIMARY KEY,
    user_id     TEXT,
    episode_id  TEXT,
    category    TEXT,     -- technical | account | content | spam
    description TEXT,
    status      TEXT DEFAULT 'pending',
                -- pending | investigating | resolved | forwarded | dismissed
    resolved_at REAL,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_episode ON user_reports (episode_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_status  ON user_reports (status, created_at);
```

**Writer:** `UserReportAgent.log_report()` (baru), `forward_to_support()` (`forwarded`),
QC pipeline (`investigating` → `resolved`). · **Reader:** `UserReportAgent` (cek duplikat), `/reports`,
`/report-stats`.

Alur status: `pending → investigating → resolved | forwarded | dismissed`. Laporan duplikat
(episode sama dalam 24 jam) masuk `dismissed` dengan catatan, bukan baris baru.

`/report-stats` = `GROUP BY episode_id ORDER BY COUNT(*) DESC` atas 7 hari terakhir.

---

## 5. `episode_schedule` — EpisodeScheduler

```sql
CREATE TABLE IF NOT EXISTS episode_schedule (
    episode_id     TEXT PRIMARY KEY,
    anime_title    TEXT NOT NULL,
    episode_number INTEGER NOT NULL,
    encoded_path   TEXT NOT NULL,
    embargo_until  REAL NOT NULL,
    regions        TEXT DEFAULT '["*"]',
    status         TEXT DEFAULT 'scheduled',
                   -- scheduled | live | cancelled | failed
    published_at   REAL,
    cancel_reason  TEXT,
    created_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedule_embargo ON episode_schedule (embargo_until, status);
```

**Writer:** `EpisodeScheduler.schedule_episode()` (baru), `cancel_schedule()`, `publish_due_episodes()`,
dan `DMCA` (`cancelled`). · **Reader:** job `episode_embargo` tiap menit, `/schedule`, `/embargo`.

Alur status: `scheduled → live` (embargo lewat) · `scheduled → cancelled` (DMCA/manual) ·
`scheduled → failed` (error publish). `live` tidak pernah kembali ke `scheduled`; koreksi setelah live
= unpublish + purge, bukan reschedule.

Dua transisi yang **harus** atomik (dipakai `cancel_schedule` vs `_publish_episode`):

```sql
-- publish: hanya kalau masih scheduled (cegah publish setelah DMCA)
UPDATE episode_schedule
   SET status='live', published_at=?
 WHERE episode_id=? AND status='scheduled';

-- cancel: hanya kalau belum live
UPDATE episode_schedule
   SET status='cancelled', cancel_reason=?
 WHERE episode_id=? AND status='scheduled';
```

Kalau `changes == 0` pada publish, berarti DMCA sudah membatalkannya — jangan publish.

---

## 6. `subtitle_tracks` — Subtitle + TranslationAgent

```sql
CREATE TABLE IF NOT EXISTS subtitle_tracks (
    episode_id   TEXT NOT NULL,
    lang         TEXT NOT NULL,        -- 'id', 'en', …
    source       TEXT,                 -- 'source' | 'deepl' | 'openai' | 'local'
    path         TEXT NOT NULL,
    qa_score     REAL,
    status       TEXT DEFAULT 'ready', -- ready | needs_review | approved | rejected
    updated_at   REAL NOT NULL,
    PRIMARY KEY (episode_id, lang)
);
```

**Writer:** `TranslationAgent.save_translated_sub()` (`ready`/`needs_review`), approval
(`approved`/`rejected`), `Subtitle` (baris `source`). · **Reader:** `/translations`,
`/approve-sub [episode_id]`, QualityChecker (semua track harus `ready`/`approved`).

`status='needs_review'` adalah satu-satunya alasan `/translations` menampilkan baris yang butuh
`/approve-sub [episode_id]`.

---

## 7. `payment_events` + `subscription_status` — PaymentAgent

```sql
CREATE TABLE IF NOT EXISTS payment_events (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    amount_idr     INTEGER,
    payment_method TEXT,
    status         TEXT DEFAULT 'pending',   -- pending | processed | failed | refunded | chargeback
    processed_at   REAL,
    created_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payments_order ON payment_events (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_user  ON payment_events (user_id, created_at);

CREATE TABLE IF NOT EXISTS subscription_status (
    user_id     TEXT PRIMARY KEY,
    plan        TEXT NOT NULL,        -- free | premium | premium_plus
    expires_at  REAL,
    retry_count INTEGER DEFAULT 0,
    grace_until REAL,
    updated_at  REAL
);
```

**Writer:** `PaymentAgent.handle_payment_webhook()` + semua handler; `subscription_status` ditulis
oleh `_handle_success()` / `_handle_renewal_failed()`. · **Reader:** `PaymentAgent`, `/payments`,
`/subscriptions`, `/refunds`, `/revenue`.

Idempotensi: `INSERT OR IGNORE` atas `payment_events.id` — Midtrans bisa mengirim notifikasi yang
sama dua kali, dan refund ganda adalah bug uang, bukan bug UI.

---

## 8. `premium_items` — pipeline premium

```sql
CREATE TABLE IF NOT EXISTS premium_items (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,       -- border | nameplate | profile_effect
    theme        TEXT,
    design_path  TEXT,
    preview_light TEXT,
    preview_dark  TEXT,
    qa_score     REAL,
    tier         TEXT,                -- basic | premium | deluxe
    price_idr    INTEGER,
    status       TEXT DEFAULT 'draft',
                 -- draft | qa_passed | priced | previewed | pending_approval
                 -- | approved | rejected | live
    created_at   REAL NOT NULL,
    updated_at   REAL
);

CREATE INDEX IF NOT EXISTS idx_items_status ON premium_items (status, created_at);
```

**Writer:** `DesignAgent` (`draft`), `QAAgent` (`qa_passed`), `PricingAgent` (`priced`),
`PreviewAgent` (`previewed`), approval (`approved`/`rejected`), `Publisher` (`live`).
· **Reader:** `/pending-items`, `/approve [id]`, `/topselling`, tombol di permission card.

Alur status: `draft → qa_passed → priced → previewed → pending_approval → approved | rejected → live`.
Satu baris = satu item; revisi menulis status baru pada baris yang sama (bukan baris baru), sehingga
`/approve` tidak pernah bingung dua item dengan id yang sama.

`/pending-items` = `status='pending_approval'`; `/approve [id]` menulis `approved` lalu memicu
Publisher. Approval dari permission card dan dari slash command menulis status yang sama.

---

## 9. `kb_articles` + `kb_meta` — knowledge base

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS kb_articles USING fts5(
    id UNINDEXED, title, body, tags, category, updated_at UNINDEXED
);

CREATE TABLE IF NOT EXISTS kb_meta (
    id         TEXT PRIMARY KEY,
    source     TEXT,        -- notion | markdown | manual
    url        TEXT,
    created_at REAL
);
```

**Writer:** `SQLiteKB.upsert()` dan `kb/ingest.py`. · **Reader:** `SupportAgent.search_kb()`,
`kb.search()` di agent lain.

`schema.sql` dibaca lewat `Path(__file__).parent / "schema.sql"` — **path absolut relatif ke file**,
bukan CWD (fix Rev 2).

Catatan FTS5:

- `snippet(kb_articles, 2, '…', '…', '...', 20)` → kolom `body`.
- `rank` (bm25) bersifat relatif; skor yang dibandingkan ke `KB_MIN_SCORE` = `-rank`.
- Kalau `KB_BACKEND=chroma`, tabel ini tidak dipakai; `kb/index.py` memilih implementasi.

---

## 10. `dlq` — dead-letter queue

```sql
CREATE TABLE IF NOT EXISTS dlq (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    payload  TEXT NOT NULL,
    ts       REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_err TEXT
);

CREATE INDEX IF NOT EXISTS idx_dlq_ts ON dlq (ts);
```

**Writer:** `DeadLetterQueue.push()` — dipanggil `bridge._post` setelah retry habis, dan
`update_biz_metrics` saat `/biz-metrics` tidak terjangkau. · **Reader/deleter:** `_flush()` tiap 30
detik (maks 50 baris), atau manual lewat `sqlite3 dlq.db`.

Aturan (fix Rev 3.1 #5):

- Flusher memakai `_send_once`, **tidak** `_post` — jadi kegagalan tidak menambah baris baru.
- Setiap percobaan menaikkan `attempts`; `attempts >= 10` → berhenti dicoba, tetap tersimpan untuk
  inspeksi manual (`sqlite3 dlq.db 'select * from dlq'`).
- Payload `{"__type": "biz_metrics", "delta": {...}}` di-replay ke `/biz-metrics`; sisanya ke `/event`.

---

## 11. `context` — SharedContext

```sql
CREATE TABLE IF NOT EXISTS context (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,     -- JSON
    owner TEXT NOT NULL,     -- role yang menulis
    ts    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_ts ON context (ts);
```

**Writer:** agent mana pun lewat `ctx.set()` / `ctx.update()` / `handoff.hand_off()`.
· **Reader:** agent penerima lewat `ctx.get()` / `ctx.find()` / `handoff.take()`; cleanup job 03.00.

Key yang dipakai (konvensi, bukan constraint):

| Pola key | Penulis | Isi |
| --- | --- | --- |
| `lead:<id>` | Sales | skor, nama, email, status |
| `ticket:<id>` | Support | tiket + history percakapan |
| `episode:<id>` | Scraper → QC | path, status pipeline, source alternatif |
| `report:<id>` | UserReportAgent | kategori, episode, aksi |
| `handoff:<from>:<to>:<id>` | siapa pun | payload handoff (AGENT-HANDOFFS.md) |

Cleanup: `DELETE FROM context WHERE ts < ?` (default 24 jam), dijadwalkan 03.00.

---

## 12. Inisialisasi

Satu pintu, dipanggil sekali saat bridge/sidecar start:

```python
# hermes_bridge/db.py
from pathlib import Path
import sqlite3

DB = Path.home() / ".hermes-office" / "hermes.db"

def connect() -> sqlite3.Connection:
    DB.parent.mkdir(mode=0o700, exist_ok=True)
    con = sqlite3.connect(str(DB), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db() -> None:
    con = connect()
    con.executescript((Path(__file__).parent / "schema_biz.sql").read_text())
    con.commit()

def migrate() -> None:
    """Idempoten: tambah kolom yang belum ada, tanpa DROP."""
    con = connect()
    cols = {r["name"] for r in con.execute("PRAGMA table_info(tickets)")}
    if "assignee" not in cols:
        con.execute("ALTER TABLE tickets ADD COLUMN assignee TEXT")
        con.commit()
```

Aturan migrasi: **tidak pernah** `DROP TABLE` atau `DROP COLUMN` otomatis. Perubahan destruktif
ditulis sebagai skrip manual di `scripts/migrations/` dan dijalankan dengan persetujuan manusia.

---

## 13. Backup

| Data | Frekuensi | Cara |
| --- | --- | --- |
| `hermes.db` | harian 02.00 | `sqlite3 hermes.db ".backup ~/.hermes-office/backup/hermes-$(date +%F).db"` |
| `kb.db` | mingguan | sama, retensi 4 file |
| `chat.db` | tidak dijadwalkan | base tidak menyediakannya; biarkan |
| `dlq.db`, `shared.db` | tidak | keduanya bisa dibuang kapan saja |

Backup job **tidak** memakai `.backup` dari proses yang sedang menulis WAL tanpa checkpoint —
jalankan `PRAGMA wal_checkpoint(TRUNCATE)` dulu, atau pakai API backup SQLite (aman untuk DB hidup).

---

## 14. `moderation_events` — Moderator (W5)

Log keputusan moderasi. **Append-only**: tidak ada kode yang `UPDATE` atau `DELETE` di tabel ini
(SECURITY.md §10 — "audit yang bisa dihapus oleh agent bukan audit").

```sql
CREATE TABLE IF NOT EXISTS moderation_events (
    id         TEXT PRIMARY KEY,          -- md-xxxxxxxxxx
    kind       TEXT NOT NULL,             -- flag | ban | unflag
    user_id    TEXT,                      -- NULL untuk flag tanpa akun
    subject    TEXT,                      -- id komentar/item
    rule       TEXT,                      -- piracy | abuse | spam | spoiler
    reason     TEXT,                      -- potongan teks yang dilanggar
    actor      TEXT NOT NULL,             -- 'Moderator'
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moderation_user ON moderation_events (user_id, created_at);
```

Aturan yang dipakai `moderator.py`: `piracy` dan `abuse` → `ban`, `spam` dan `spoiler` → `flag`.
Status ban dihitung dari baris **terakhir** milik `user_id` (`ModeratorAgent.is_banned`), jadi
"unban" nanti cukup menambah baris baru — bukan menghapus yang lama.

---

## 15. Data growth (W6) — file dan satu tabel milik AniWatch

Tidak ada tabel baru di `hermes.db` untuk W6. Analytics menulis file, bukan baris:

| Berkas | Ditulis oleh | Isi |
| --- | --- | --- |
| `media/published/analytics/YYYY-MM-DD.json` | Analytics | snapshot `{generated_at, source, feed, local, dropoffs, insufficient}` |
| `media/published/reports/weekly-<ISO week>.md` | Marketing | laporan mingguan, tiap bagian menyebut sumber angkanya |
| `media/published/meta/<episode_id>.json` | SEO | `<title>`/og per episode |
| `media/published/sitemap.xml` | SEO | hanya episode `status='live'` |
| `media/published/structured-data.json` | SEO | JSON-LD `TVEpisode` |
| `media/published/recommendations.jsonl` | Recommendation | dipakai kalau `RECOMMENDATION_DB` kosong |

Satu tabel ditulis **di luar** DB ini, di file `RECOMMENDATION_DB` milik AniWatch. Batch membuatnya
kalau belum ada dan hanya pernah `INSERT OR REPLACE`:

```sql
CREATE TABLE IF NOT EXISTS recommendations (
    user_id    TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    score      REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, episode_id)
);
```

**Writer:** `RecommendationAgent.save_recs()` (Minggu 22.00). · **Reader:** situs AniWatch.
**Umur data:** satu baris per (user, episode), ditimpa tiap batch — skor lama tidak menumpuk.
Sumber angka tontonan (`ANALYTICS_FEED`) juga file milik situs, bukan tabel di fork ini
(ENV-VARS.md §3d); tidak ada DDL baru yang perlu dimigrasi.
