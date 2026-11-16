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
| `KB_MIN_SCORE` | tidak | float | `0.5` | `agents/support.py` | ambang relevansi FTS5 (relatif!) |
| `LOG_LEVEL` | tidak | enum | `INFO` | semua Python | `DEBUG` \| `INFO` \| `WARNING` |

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
| `IMAGE_GEN_API_KEY` | DesignAgent | DesignAgent berhenti di langkah pertama |
| `IMAGE_GEN_PROVIDER` | DesignAgent | default `stability` (`dalle` \| `stability`) |
| `CDN_API_KEY` | Encoder, Publisher, DMCA | upload/purge CDN gagal → `agent_error` |
| `CDN_BASE_URL` | idem | URL file tidak bisa dibentuk |
| `TRANSLATION_PROVIDER` | TranslationAgent | default `deepl` (`deepl` \| `openai` \| `local`) |
| `DEEPL_API_KEY` | TranslationAgent (kalau `deepl`) | guard: provider `deepl` tanpa key = error saat start agent |
| `TRANSLATION_QA_THRESHOLD` | TranslationAgent | default `0.75`; di bawah ini → permission card |

Prinsip: integrasi opsional **tidak** boleh menggagalkan agent lain. Yang hilang hanya tool terkait,
dan itu harus terlihat sebagai `agent_error` yang jelas, bukan `except: pass`.

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

# ── Agent ──────────────────────────────────────────────────────────────────
HERMES_MODEL=nous-hermes-2
OLLAMA_URL=http://127.0.0.1:11434
KB_BACKEND=sqlite
KB_MIN_SCORE=0.5
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
| `bridge.py` | `os.getenv` saat import | bridge tidak memanggil `load_dotenv`; sidecar yang memuat |
| `webhook_server/main.py` | `load_dotenv()` di awal | satu-satunya pemuat `.env` |
| Agent | `os.getenv` saat dipakai | jangan baca env di dalam loop panas |
| Scheduler | idem | — |

Kenapa bridge tidak memuat `.env` sendiri: satu file `.env`, satu pemuat, satu sumber kebenaran.
Bridge selalu dijalankan oleh sidecar (in-process) atau oleh skrip yang sudah `source .env`.

---

## 6. Checklist kebocoran

- [ ] `.env` ada di `.gitignore`
- [ ] `.env.example` tidak berisi nilai asli
- [ ] token tidak muncul di log (`_log.warning("... %s", e)` — jangan log header)
- [ ] token tidak dikirim ke UI; jangan pernah `broadcast` payload event yang membawa header
- [ ] `~/.agent-office/auth-token` mode `0600`, `~/.agent-office/` mode `0700`
- [ ] `doctor` hijau: `npm run doctor` mengecek port, token, dan permission file
