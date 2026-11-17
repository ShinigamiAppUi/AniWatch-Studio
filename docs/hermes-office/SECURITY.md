# Hermes Office — Security Model

Nov 16, 2026 · @Shin · Mengikat semua proses. Env: [ENV-VARS.md](ENV-VARS.md).

Kantor ini menyimpan prompt, balasan, task, dan data bisnis (tiket, payment, laporan user). Model
keamanannya sederhana dan **tidak** multi-tenant: **satu mesin, satu pengguna, loopback saja.**

---

## 1. Aset yang dilindungi

| Aset | Di mana | Kalau bocor |
| --- | --- | --- |
| Token kantor | `~/.agent-office/auth-token` (0600) | siapa pun bisa mengirim event palsu & membaca chat |
| Prompt & balasan | `chat.db` (0600) | isi percakapan kerja |
| Data bisnis | `hermes.db` | tiket, payment, laporan user |
| Secret integrasi | `.env` | Gmail, Midtrans, CDN, Telegram |
| Knowledge base | `kb.db` | biasanya publik, tapi bisa memuat proses internal |

---

## 2. Batas kepercayaan

```
[ mesin ini, user ini ]  ── dipercaya ──▶  Express :3334, sidecar :8765, bridge
        │
        └── tidak dipercaya ──▶ webhook luar, Midtrans, API pihak ketiga, isi pesan user
```

Semua yang datang dari luar (webhook, payload Midtrans, email, komentar, laporan user) adalah
**input tidak tepercaya**: divalidasi, di-clamp, dan tidak pernah dieksekusi sebagai perintah.
Prompt injection di isi tiket tidak boleh mengubah routing — agent hanya boleh memakai data itu
sebagai isi balasan.

---

## 3. Binding

| Proses | Bind | Aturan |
| --- | --- | --- |
| Express | `127.0.0.1` saja | `AGENT_OFFICE_HOST` menolak selain loopback + fallback (base) |
| Sidecar | `127.0.0.1` eksplisit | **jangan** `--host 0.0.0.0`, jangan diteruskan lewat reverse proxy |
| Ollama | `127.0.0.1` | default Ollama; jangan expose ke LAN |

Kalau butuh akses dari HP, pakai **phone mode base** (`npm run lan`) yang punya gate sendiri
(token UI + secret + allowlist route). Jangan membuka bind server.

---

## 4. Autentikasi

### 4.1 Kantor (Express)

- Token Bearer dari `~/.agent-office/auth-token`, mode `0600`, direktori `0700`.
- Wajib untuk `POST /event`, `POST /biz-metrics`, `/chat/reply`, `/a2a`.
- Token UI (`#token=` di URL) hanya untuk aksi UI: `POST /settings`, jawab permission.
- Rotasi: `npm run rotate-token` → token lama langsung mati. Bridge akan 401 → DLQ. Perbarui `.env`
  dan restart bridge; **jangan** menonaktifkan auth untuk "sementara".

### 4.2 Sidecar (FastAPI)

- `POST /webhook` → header `X-Webhook-Secret` harus sama dengan `WEBHOOK_SECRET`.
- `POST /approval-callback` → hanya dari `biz-events.js` (loopback). Tidak punya secret sendiri:
  keamanannya adalah binding loopback. Karena itu **sidecar tidak boleh bind non-loopback**, titik.
- `POST /command` (W7) → slash command bisnis dari chat (`/design`, `/pending-items`, `/approve`),
  juga tanpa secret sendiri dan dengan alasan yang sama: perelainya `server/biz-events.js` di mesin
  yang sama. Isinya hanya tiga command itu (`webhook_server/commands.py`); baris lain dijawab
  `handled: false` dan tidak melakukan apa pun.
- `POST /webhook/payment` → signature SHA-512 Midtrans (lihat §5).
- `GET /approval/{id}` → read-only, loopback.

### 4.3 Webhook payload

```python
if x_webhook_secret != WEBHOOK_SECRET:          # constant-time compare
    raise HTTPException(403, "invalid secret")
if payload.type not in SUPPORTED_TRIGGERS:
    raise HTTPException(400, f"trigger type tidak dikenal: {payload.type}")
```

Pakai `secrets.compare_digest`, bukan `==`, untuk secret dan signature.

---

## 5. Signature Midtrans (jangan pernah disederhanakan)

```python
raw = (
    f"{payload.get('order_id', '')}"
    f"{payload.get('status_code', '')}"
    f"{payload.get('gross_amount', '')}"
    f"{MIDTRANS_SERVER_KEY}"
)
expected = hashlib.sha512(raw.encode("utf-8")).hexdigest()
if not secrets.compare_digest(x_signature_key or "", expected):
    raise HTTPException(403, "invalid signature")
```

Tiga kesalahan yang pernah ada di rancangan dan tidak boleh kembali:

1. `.encode()` tanpa `utf-8` (implicit, berbeda di platform tertentu).
2. `payload['order_id']` tanpa `.get()` → `KeyError` jadi 500, bukan 403.
3. Verifikasi dimatikan karena `MIDTRANS_SERVER_KEY` kosong → sekarang `RuntimeError` saat startup.

Idempotensi: `payment_events.id` unik, `INSERT OR IGNORE`. Notifikasi ganda tidak boleh menghasilkan
refund ganda.

---

## 6. Hook Claude Code

Base menandatangani request hook (nonce + proof). Fork ini **tidak mengubah** itu. Aturan:

- Jangan menambah route baru yang menerima request bertanda tangan tanpa memeriksa tanda tangannya.
- Jangan melemahkan `requireToken` untuk mempermudah debugging; pakai `curl` dengan token.
- `npm run doctor` memeriksa mode file token; jalankan setelah setiap perubahan permission.

---

## 7. Least privilege untuk agent

| Agent | Boleh | Tidak boleh |
| --- | --- | --- |
| Sales | baca/tulis lead, kirim email ke lead, update CRM | akses payment, hapus data |
| Support | baca tiket, KB, kirim balasan | ubah harga, refund |
| PaymentAgent | refund **setelah** approval, cabut item | mengubah plan tanpa event payment |
| Publisher | upload CDN, aktifkan item **setelah** approval | menulis harga |
| DMCA | unpublish, purge CDN | menghapus bukti/audit log |
| SecOps | ban IP, rate limit, flag akun | menghapus akun, mengubah role |
| Orchestrator | route, delegasi, eskalasi | melakukan pekerjaan agent lain |

Implementasi: setiap agent hanya meng-import tool yang ia butuhkan, dan tool yang mengubah uang atau
publikasi wajib lewat `agent_waiting` + `wait_for_approval`. Ini bukan sekadar konvensi — reviewer
menolak PR yang memberi `process_refund` ke agent lain.

---

## 8. Penanganan input

| Input | Perlakuan |
| --- | --- |
| Isi tiket/email/komentar | disimpan apa adanya, dipakai sebagai **data**; jangan pernah dijadikan bagian prompt sistem |
| Payload webhook | divalidasi tipe + `.get()` untuk semua field |
| `delta` metrics | `Number.isFinite` filter; key asing diabaikan |
| Nama file dari user | tidak pernah dipakai sebagai path; pakai id internal |
| URL dari webhook | diambil hanya lewat allowlist domain per agent |
| Teks chat | di-clamp server base (200 / `MAX_TEXT_LEN`) — jangan menambah field bebas baru |

Khusus prompt injection: agent yang membaca konten user (Support, Moderator, UserReportAgent) harus
mempunyai instruksi sistem yang menyatakan bahwa isi pesan adalah **keluhan**, bukan perintah.
Routing tetap ditentukan `route_trigger()`, bukan isi pesan.

---

## 9. Rahasia

- `.env` tidak di-commit; `.env.example` tanpa nilai.
- Jangan log header, token, atau payload payment penuh. Log id, bukan rahasia.
- Jangan kirim secret ke browser. UI tidak pernah butuh `OFFICE_TOKEN`.
- Jangan menyimpan secret di DB (kecuali perlu enkripsi; saat ini tidak ada).
- Kalau ada secret yang tidak sengaja ter-commit: **rotate dulu**, baru bersihkan history.

---

## 10. Audit

| Kejadian | Di mana dicatat | Retensi |
| --- | --- | --- |
| Trigger masuk | log sidecar `trigger=<type> source=<source>` | log file |
| Approval diputuskan | `payment_events` / `premium_items` + log | permanen (DB) |
| Takedown DMCA | log DMCA + status `cancelled` | permanen |
| Pelanggaran SecOps | log incident + aksi | 30 hari |
| Event gagal | `dlq` (dengan `attempts`, `last_err`) | sampai manual |

Audit yang bisa dihapus oleh agent bukan audit. `dmca.py` dan `sec_ops.py` hanya menambah baris,
tidak pernah menghapus.

---

## 11. Checklist keamanan rilis

- [ ] `npm run doctor` green (port, token, permission)
- [ ] `curl -s -o /dev/null -w '%{http_code}' http://<LAN-IP>:3334/health` → gagal konek (bukan 200)
- [ ] `ss -ltnp | grep -E '3334|8765'` → hanya `127.0.0.1`
- [ ] `POST /event` tanpa token → 401
- [ ] `POST /webhook` tanpa secret → 403
- [ ] `POST /webhook/payment` dengan signature salah → 403
- [ ] `grep -rE "(api[_-]?key|token|secret)\s*=\s*['\"][^'\"]{8,}" --include=*.py --include=*.js .` → kosong
- [ ] `.env` ada di `.gitignore`, `git status` tidak menampilkannya
- [ ] file `~/.agent-office/auth-token` mode `600`, direktori `700`
- [ ] log tidak memuat token (`grep -i "bearer\|authorization" log/*.log` → kosong)
