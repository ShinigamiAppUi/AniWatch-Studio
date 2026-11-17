# Hermes Office — Environment Variables

Nov 16, 2026 · @Shin · Sumber tunggal untuk nama env var.

Aturan yang tidak bisa dinegosiasikan:

1. **Tidak ada secret di kode, config, atau repo.** Semua lewat env / `.env` (tidak di-commit).
2. **Tidak ada `.dev.vars`.** Kalau ada, Wrangler/shell bisa membaca file yang salah.
3. **Nama yang sama dipakai di semua bahasa.** `SIDECAR_URL` di Python, di `.env`, dan di
   `biz-events.js` — bukan `HERMES_SIDECAR_URL` di salah satu tempat (fix Rev 3 #3).
4. **Gagal cepat untuk secret wajib.** Sidecar `raise RuntimeError` saat start kalau
   `WEBHOOK_SECRET` atau `MIDTRANS_SERVER_KEY` kosong (fix Rev 3 #7).

---

## 1. Base (warisan Claude-Office)

| Variabel | Wajib | Tipe | Default | Dipakai | Arti |
| --- | --- | --- | --- | --- | --- |
| `AGENT_OFFICE_PORT` | tidak | int 1–65535 | `3334` | server, hook, doctor, Vite, desktop | port Express/WS |
| `AGENT_OFFICE_UI_PORT` | tidak | int | `3333` | Vite, allowlist origin | port UI |
| `AGENT_OFFICE_HOST` | tidak | string | `127.0.0.1` | server | hanya `127.0.0.1`/`localhost` diterima; selain itu ditolak + fallback |
| `AGENT_OFFICE_HOME` | tidak | path | `~/.agent-office` | semua proses kantor | direktori token & DB kantor |
| `CLAUDE_CONFIG_DIR` | tidak | path | `~/.claude` | `install-hooks.sh` | lokasi `settings.json` Claude Code |

### `OFFICE_TOKEN` — cara mengambilnya

Bukan env yang dibuat sendiri. Isinya **file token base**:

```bash
# file 0600 milik server; dibuat otomatis saat server pertama kali start
cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token"
```

Di `.env` sisi Python:

```bash
OFFICE_TOKEN=$(cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token")
```

Kalau server dijalankan ulang setelah `npm run rotate-token`, token lama langsung mati — bridge akan
menerima 401 dan semua event masuk DLQ. Itu perilaku yang benar: perbarui env, restart bridge.

---

## 2. Bridge & sidecar

| Variabel | Wajib | Tipe | Default | Dipakai | Arti |
| --- | --- | --- | --- | --- | --- |
| `OFFICE_URL` | tidak | URL | `http://127.0.0.1:3334` | `bridge.py`, `queue.py` | alamat Express |
| `OFFICE_TOKEN` | **ya** | string | — | `bridge.py` | Bearer token (isi `auth-token`) |
| `SIDECAR_URL` | tidak | URL | `http://127.0.0.1:8765` | `bridge.py`, `biz-events.js` | alamat FastAPI |
| `WEBHOOK_SECRET` | **ya** | string | — | `webhook_server/main.py` | header `X-Webhook-Secret` |
| `MIDTRANS_SERVER_KEY` | **ya** | string | — | `webhook_server/main.py` | verifikasi signature SHA-512 |
| `HERMES_MODEL` | tidak | string | `nous-hermes-2` | agent, Ollama | model yang dipanggil |
| `OLLAMA_URL` | tidak | URL | `http://127.0.0.1:11434` | agent | endpoint Ollama |
| `KB_BACKEND` | tidak | enum | `sqlite` | `kb/index.py` | `sqlite` \| `chroma` |
| `KB_MIN_SCORE` | tidak | float | `0.5` | `hermes_agents/kb.py` | ambang relevansi FTS5 (relatif!) |
| `LOG_LEVEL` | tidak | enum | `INFO` | semua Python | `DEBUG` \| `INFO` \| `WARNING` |
| `HERMES_TZ` | tidak | string | `Asia/Jakarta` | `webhook_server/scheduler.py` | zona waktu job APScheduler |

`MIDTRANS_SERVER_KEY` wajib walau PaymentAgent belum dipakai: tanpa itu endpoint
`/webhook/payment` menerima notifikasi palsu tanpa verifikasi. Kalau memang belum ada Midtrans,
set nilai acak panjang — jangan kosongkan, dan jangan matikan verifikasi.

---

## 3. Integrasi luar (semua opsional, per agent)

| Variabel | Dipakai | Kalau kosong |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` | Sales, Support (Gmail API) | email tidak dikirim; agent melapor `agent_error` "email belum dikonfigurasi" |
| `GOOGLE_CLIENT_SECRET` | idem | idem |
| `GOOGLE_REFRESH_TOKEN` | idem | idem |
| `HUBSPOT_API_KEY` | Sales (CRM) | `update_crm` jadi no-op + warning di log |
| `NOTION_TOKEN` | `kb/ingest.py --source notion` | ingest Notion dinonaktifkan |
| `DISCORD_WEBHOOK_URL` | SocialMedia, Notifier | post Discord dilewati |
| `TELEGRAM_BOT_TOKEN` | SocialMedia, Notifier | post Telegram dilewati |
| `TELEGRAM_CHANNEL_ID` | idem | idem |
| `TWITTER_BEARER_TOKEN` | SocialMedia | post X dilewati |
| `IMAGE_GEN_API_KEY` | DesignAgent (rencana) | **tidak dipanggil**: W7 membuat desain dari template SVG, dan context mencatat `image_gen: "belum diimplementasikan"` kalau variabel ini diisi |
| `IMAGE_GEN_PROVIDER` | DesignAgent (rencana) | idem — tidak ada provider image-gen yang dipanggil fork ini |
| `CDN_API_KEY` | Encoder, Publisher, DMCA | upload/purge CDN gagal → `agent_error` |
| `CDN_BASE_URL` | idem | URL file tidak bisa dibentuk |
| `TRANSLATION_PROVIDER` | TranslationAgent | default `deepl` (`deepl` \| `openai` \| `local`) |
| `DEEPL_API_KEY` | TranslationAgent (kalau `deepl`) | guard: provider `deepl` tanpa key = error saat start agent |
| `TRANSLATION_QA_THRESHOLD` | TranslationAgent | default `0.75`; di bawah ini → permission card |

### 3a. Pipeline episode (W3) — dipakai `hermes_agents/`

| Variabel | Wajib | Default | Arti |
| --- | --- | --- | --- |
| `HERMES_MEDIA_DIR` | tidak | `~/.hermes-office/media` | akar file: `incoming/`, `encoded/`, `subs/`, `published/` |
| `HERMES_ENCODER` | tidak | `ffmpeg` | `ffmpeg` (encode 720p asli) atau `copy` (dev tanpa ffmpeg; dicatat `encode_mode: copy`) |
| `HERMES_GLOSSARY` | tidak | `~/.hermes-office/glossary/id-en.json` | kamus `local` untuk TranslationAgent |
| `TRANSLATION_MODEL` | tidak | `gpt-4o-mini` | model kalau `TRANSLATION_PROVIDER=openai` |
| `OPENAI_API_KEY` | hanya kalau `openai` | — | key untuk provider `openai` |

`TRANSLATION_PROVIDER` default di kode sekarang **`local`** (glossary), bukan `deepl`: tanpa key,
`deepl`/`openai` gagal jelas (`MissingCredentials`), bukan diam-diam pindah provider.

### 3b. Kanal keluar Support (W5) — `hermes_agents/mailer.py`

Balasan Support dikirim lewat **SMTP** (stdlib `smtplib`), bukan Gmail API: tanpa OAuth, tanpa
dependensi baru, dan provider apa pun yang punya endpoint SMTP bisa dipakai. Baris `GOOGLE_*` di
§3 tetap untuk agent lain.

| Variabel | Wajib | Default | Arti |
| --- | --- | --- | --- |
| `SMTP_HOST` | ya, untuk mengirim | — (kosong) | kalau kosong, balasan **gagal** dengan alasan `SMTP belum dikonfigurasi`; tiket tetap `open` |
| `SMTP_PORT` | tidak | `587`/`465`/`25` | default ikut `SMTP_SECURITY` |
| `SMTP_SECURITY` | tidak | `starttls` | `starttls` \| `ssl` \| `none` (nilai aneh → `starttls`) |
| `SMTP_USER` | tidak | — | kalau diisi, `login()` dipanggil |
| `SMTP_PASSWORD` | tidak | — | jangan pernah ditulis di `.env.example` |
| `SUPPORT_FROM` | tidak | `SMTP_USER` atau `support@aniwatch.example` | alamat pengirim di header `From` |
| `SUPPORT_FROM_NAME` | tidak | `AniWatch Support` | nama pengirim |
| `SMTP_TIMEOUT_S` | tidak | `15` | timeout koneksi/kirim |
| `HERMES_OUTBOX` | tidak | `~/.hermes-office/outbox/replies.jsonl` | catatan **setiap** percobaan kirim (berhasil maupun gagal), 0600 |

### 3c. Kanal masuk Support (W5) — `hermes_agents/inbox.py`

Membaca kotak masuk juga lewat stdlib (`imaplib`, TLS wajib), bukan Gmail API — `SMTP_*` dan
`IMAP_*` biasanya menunjuk akun yang sama, jadi cukup satu mailbox untuk dua arah.

| Variabel | Wajib | Default | Arti |
| --- | --- | --- | --- |
| `IMAP_HOST` | ya, untuk membaca | — (kosong) | kalau kosong, `email_check` log sekali per jam dan tidak membuat tiket |
| `IMAP_PORT` | tidak | `993` | selalu `IMAP4_SSL` |
| `IMAP_USER` | ya, untuk membaca | — | login; biasanya sama dengan `SMTP_USER` |
| `IMAP_PASSWORD` | tidak | — | app password Gmail/Fastmail; jangan ditulis di `.env.example` |
| `IMAP_FOLDER` | tidak | `INBOX` | folder yang dibaca |
| `IMAP_MAX_PER_RUN` | tidak | `10` | batas pesan per putaran (1–50); sisanya menunggu 5 menit berikutnya |

Pesan dengan header `Auto-Submitted` selain `no` dilewati (itu balasan otomatis kita sendiri), dan
UID yang sudah jadi tiket disimpan di SharedContext (`inbox:seen`) sehingga satu email tidak pernah
menghasilkan dua tiket.

Kegagalan kirim **bukan** pengecualian: `mailer.send()` mengembalikan `{sent, error}`, outbox mencatat,
tiket tetap `open` sehingga kartu SLA berikutnya menagihnya. Status terakhir terlihat di `GET /health`
(`mail.configured`, `mail.last`).

Prinsip: integrasi opsional **tidak** boleh menggagalkan agent lain. Yang hilang hanya tool terkait,
dan itu harus terlihat sebagai `agent_error` yang jelas, bukan `except: pass`.

### 3d. Growth (W6) — `hermes_agents/growth_data.py`

Tiga variabel, semuanya opsional. Tidak satu pun dipalsukan: batch Minggu 22.00 tetap jalan tanpa
keduanya, menulis ke `media/published/recommendations.jsonl`, dan menyebut alasannya di log.

| Variabel | Wajib | Default | Arti |
| --- | --- | --- | --- |
| `ANALYTICS_FEED` | tidak | — (kosong) | file export AniWatch (JSON): `{"generated_at", "episodes":[{"episode_id","views","watch_time_s","completions"}], "history":[{"user_id","episode_id"}]}`. Dibaca Analytics (drop-off), Recommendation (model) dan laporan mingguan Marketing |
| `RECOMMENDATION_DB` | tidak | — (kosong) | file SQLite milik AniWatch; kalau diisi, batch menulis tabel `recommendations (user_id, episode_id, score, created_at)` (dibuat kalau belum ada). Kalau kosong → `media/published/recommendations.jsonl` |
| `SEO_SITE_URL` | tidak | `CDN_BASE_URL`, lalu URL relatif | origin publik untuk `sitemap.xml`, `meta/<episode>.json` dan `structured-data.json` |

`ANALYTICS_FEED` adalah **satu-satunya** jalan angka tontonan masuk ke fork ini: tidak ada API
AniWatch yang bisa dipanggil dari sini. Tanpa file itu, Analytics tetap menulis snapshot dari data
lokal (episode live, tiket, laporan user) dengan `source: "local"`, dan `insufficient` menyebut apa
yang belum bisa dihitung — bukan angka karangan. Kanal sosial tidak butuh variabel baru:
`DISCORD_WEBHOOK_URL` dan `TELEGRAM_*` di §3 dipakai SocialMedia (satu post per channel per
episode), sedangkan X ditandai "belum diimplementasikan" karena bearer token hanya bisa baca.

---

## 4. `.env.example`

Disalin ke `.env` saat setup. Jangan pernah mengisi nilai asli di file contoh ini.

```bash
# ── Kantor (base) ───────────────────────────────────────────────────────────
AGENT_OFFICE_PORT=3334
AGENT_OFFICE_UI_PORT=3333
# AGENT_OFFICE_HOME=~/.agent-office

# ── Bridge ─────────────────────────────────────────────────────────────────
OFFICE_URL=http://127.0.0.1:3334
# OFFICE_TOKEN: salin dari $AGENT_OFFICE_HOME/auth-token, jangan hardcode
OFFICE_TOKEN=
SIDECAR_URL=http://127.0.0.1:8765

# ── Sidecar (WAJIB) ────────────────────────────────────────────────────────
WEBHOOK_SECRET=
MIDTRANS_SERVER_KEY=

# ── Pipeline episode (W3) ──────────────────────────────────────────────────
# HERMES_MEDIA_DIR=~/.hermes-office/media
# HERMES_ENCODER=ffmpeg        # 'copy' hanya untuk dev tanpa ffmpeg
# HERMES_GLOSSARY=~/.hermes-office/glossary/id-en.json
# TRANSLATION_PROVIDER=local   # local | deepl | openai

# ── Agent ──────────────────────────────────────────────────────────────────
HERMES_MODEL=nous-hermes-2
OLLAMA_URL=http://127.0.0.1:11434
KB_BACKEND=sqlite
KB_MIN_SCORE=0.5
# --- Kanal keluar Support (W5) -------------------------------------------
# Tanpa SMTP_HOST, balasan Support gagal dengan alasan yang jelas dan tiket
# tetap open (bukan diam-diam dianggap terkirim).
# SMTP_HOST=smtp.contoh.com
# SMTP_PORT=587
# SMTP_SECURITY=starttls      # starttls | ssl | none
# SMTP_USER=
# SMTP_PASSWORD=
SUPPORT_FROM=support@aniwatch.example
SUPPORT_FROM_NAME=AniWatch Support
# SMTP_TIMEOUT_S=15
# HERMES_OUTBOX=~/.hermes-office/outbox/replies.jsonl

# ── Growth (W6) ────────────────────────────────────────────────────────────
# ANALYTICS_FEED=~/.hermes-office/aniwatch-export.json
# RECOMMENDATION_DB=~/.hermes-office/aniwatch.db
# SEO_SITE_URL=https://aniwatch.example

LOG_LEVEL=INFO

# ── Integrasi (opsional) ───────────────────────────────────────────────────
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GOOGLE_REFRESH_TOKEN=
# HUBSPOT_API_KEY=
# NOTION_TOKEN=
# DISCORD_WEBHOOK_URL=
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHANNEL_ID=
# TWITTER_BEARER_TOKEN=
# IMAGE_GEN_API_KEY=
IMAGE_GEN_PROVIDER=stability
# CDN_API_KEY=
# CDN_BASE_URL=
TRANSLATION_PROVIDER=deepl
# DEEPL_API_KEY=
TRANSLATION_QA_THRESHOLD=0.75
```

---

## 5. Di mana tiap proses membaca env

| Proses | Cara memuat | Catatan |
| --- | --- | --- |
| Express (`server/index.js`) | `process.env` | hanya butuh `AGENT_OFFICE_*` |
| `biz-events.js` | `process.env.SIDECAR_URL` | **tidak** butuh token sidecar |
| `bridge.py` | `os.getenv` di setiap panggilan | tidak ada I/O saat import; `init()` membuka DLQ |
| `webhook_server/main.py` | `hermes_bridge.env.load_env()` | satu fungsi pemuat, dipakai semua entry point |
| Pipeline / selfcheck / smoke | `load_env()` di `main()` | `python -m hermes_agents.pipeline`, `...selfcheck`, `...hermes_bridge.smoke` |
| Agent | `os.getenv` saat dipakai | jangan baca env di dalam loop panas |
| Scheduler | idem | — |

Kenapa bridge tidak memuat `.env` sendiri: satu file `.env`, satu pemuat, satu sumber kebenaran.
Yang memuat adalah **entry point** lewat `hermes_bridge/env.py`; `bridge.py` tetap import-safe dan
membaca `OFFICE_URL` / `SIDECAR_URL` di setiap panggilan, jadi variabel yang di-set setelah import
(tombol `.env`, `export`, atau override satu kali jalan) tetap dipakai event berikutnya.

Nilai yang sudah ada di environment **menang** atas `.env`. Bentuk `OFFICE_TOKEN=$(cat ...)` dan
`${VAR:-default}` ikut dibaca, karena itu yang dipakai `.env.example`.

---

## 6. Checklist kebocoran

- [ ] `.env` ada di `.gitignore`
- [ ] `.env.example` tidak berisi nilai asli
- [ ] token tidak muncul di log (`_log.warning("... %s", e)` — jangan log header)
- [ ] token tidak dikirim ke UI; jangan pernah `broadcast` payload event yang membawa header
- [ ] `~/.agent-office/auth-token` mode `0600`, `~/.agent-office/` mode `0700`
- [ ] `doctor` hijau: `npm run doctor` mengecek port, token, dan permission file

---

## 7. Tips & gotchas

**`OFFICE_TOKEN` bukan token karangan.** Nilainya harus sama dengan isi
`$AGENT_OFFICE_HOME/auth-token`. `openssl rand -hex 32` menghasilkan token yang **tidak** dikenal
server → setiap `POST /event` dijawab 401, dan event menumpuk di DLQ tanpa satu pun karakter muncul.
Satu-satunya perintah yang benar:

```bash
echo "OFFICE_TOKEN=$(cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token")" >> .env
```

Setelah `npm run rotate-token`, token lama langsung mati — perbarui `.env` **dan** restart bridge,
kalau tidak semua event masuk DLQ (dan itu terlihat seperti "kantor tidak menerima apa pun").

**`SIDECAR_URL` dibaca dua bahasa.** `hermes_bridge/bridge.py` dan `server/biz-events.js` harus
membaca nama yang sama. Ini fix Rev 3 #3; jangan pernah memperkenalkan `HERMES_SIDECAR_URL`.

**Jangan bind `0.0.0.0`.** Sidecar: `--host 127.0.0.1`. Express sudah loopback dari base. Kalau
butuh akses HP, pakai phone mode base (`npm run lan`), bukan membuka bind.

**Ubah `.env` = restart.** Tidak ada hot-reload env di Python. Restart sidecar (dan bridge kalau
dijalankan terpisah); scheduler membaca env saat start.

**Opsional tapi dependen.** Variabel di bawah "opsional" hanya selama fiturnya tidak dipakai:

| Fitur dipakai | Variabel yang jadi wajib | Kalau kosong |
| --- | --- | --- |
| `TRANSLATION_PROVIDER=deepl` | `DEEPL_API_KEY` | agent berhenti dengan `agent_error` jelas |
| Publisher / Encoder | `CDN_API_KEY`, `CDN_BASE_URL` | upload gagal, item tidak pernah live |
| Support lewat Gmail | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | `check_new_emails` log sekali per jam, bukan tiap 5 menit |
| Sales lewat HubSpot | `HUBSPOT_API_KEY` | `update_crm` jadi no-op + warning |
| DesignAgent | `IMAGE_GEN_API_KEY` (+ `IMAGE_GEN_PROVIDER`) | tidak berpengaruh: desain dari template SVG, dan hasilnya menyebutkan itu |
| Notifier / SocialMedia | `DISCORD_WEBHOOK_URL`, `TELEGRAM_*` | platform itu dilewati (`skipped` menyebut nama variabelnya), feed tetap ditulis |
| Recommendation batch | `RECOMMENDATION_DB` | ditulis ke `media/published/recommendations.jsonl` |
| Analytics / Marketing | `ANALYTICS_FEED` | hanya data lokal; angka tontonan dan drop-off dinyatakan belum ada |

Aturan umum: integrasi opsional yang kosong **tidak** boleh menggagalkan agent lain, dan tidak boleh
diam-diam (`except: pass`). Yang hilang hanya tool terkait, dan itu harus terlihat di bubble merah.

**Jangan menaruh secret di tempat lain.** Bukan di `office.config.json`, bukan di kode, bukan di DB,
bukan di argumen CLI (terlihat di `ps`), bukan di URL (masuk history). Hanya `.env` atau secret store
OS.

**Jangan log header.** `_log.warning("... %s", e)` boleh; mencetak `headers` atau URL dengan token
tidak. `SECURITY.md` §11 punya perintah grep untuk memeriksanya sebelum rilis.
