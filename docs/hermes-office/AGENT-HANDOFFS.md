# Hermes Office — Agent Handoff Protocol

Nov 16, 2026 · @Shin · Mengikat `hermes_bridge/shared_context.py` dan semua agent.
Katalog agent: [AGENTS.md](AGENTS.md). Skema tabel `context`: [DB-SCHEMA.md](DB-SCHEMA.md) §11.

Masalah yang diselesaikan: Sales tahu leadnya, Marketing tidak. Support tahu kronologi tiket,
Orchestrator tidak. Tanpa kontrak, setiap agent akan mengirim context lewat `import` antar modul
(ketergantungan melingkar) atau lewat LLM (tidak deterministik). Keduanya salah.

**Aturan utama: agent tidak pernah memanggil agent lain secara langsung.** Mereka menulis context,
lalu Orchestrator (atau agent penerima lewat trigger) yang memutuskan.

---

## 1. SharedContext

Satu kelas, thread-safe, SQLite, umur 24 jam.

```python
# hermes_bridge/shared_context.py
import json, sqlite3, threading, time
from pathlib import Path

DB = Path.home() / ".hermes-office" / "shared.db"

class SharedContext:
    """State antar agent. Thread-safe: banyak agent jalan bersamaan di satu proses."""

    def __init__(self, db_path: Path | None = None):
        path = db_path or DB
        path.parent.mkdir(mode=0o700, exist_ok=True)
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.execute("""
            CREATE TABLE IF NOT EXISTS context (
                key TEXT PRIMARY KEY, value TEXT NOT NULL,
                owner TEXT NOT NULL, ts REAL NOT NULL
            )
        """)
        self._con.execute("CREATE INDEX IF NOT EXISTS idx_context_ts ON context (ts)")
        self._con.commit()
        self._lock = threading.Lock()

    def set(self, key: str, value: dict, owner: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO context VALUES (?,?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), owner, time.time()),
            )
            self._con.commit()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._con.execute("SELECT value FROM context WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, key: str, patch: dict, owner: str) -> dict:
        """Baca-ubah-tulis atomik. Dua agent boleh menambah field berbeda."""
        with self._lock:
            row = self._con.execute("SELECT value FROM context WHERE key=?", (key,)).fetchone()
            data = json.loads(row[0]) if row else {}
            data.update(patch)
            self._con.execute(
                "INSERT OR REPLACE INTO context VALUES (?,?,?,?)",
                (key, json.dumps(data, ensure_ascii=False), owner, time.time()),
            )
            self._con.commit()
        return data

    def delete(self, key: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM context WHERE key=?", (key,))
            self._con.commit()

    def find(self, prefix: str, limit: int = 50) -> list[tuple[str, dict]]:
        with self._lock:
            rows = self._con.execute(
                "SELECT key, value FROM context WHERE key LIKE ? ORDER BY ts DESC LIMIT ?",
                (prefix + "%", limit),
            ).fetchall()
        return [(k, json.loads(v)) for k, v in rows]

    def cleanup_older_than(self, seconds: int = 86400) -> int:
        cutoff = time.time() - seconds
        with self._lock:
            cur = self._con.execute("DELETE FROM context WHERE ts < ?", (cutoff,))
            self._con.commit()
        return cur.rowcount
```

Kenapa `update()` ada: tanpa itu, dua agent yang menulis key sama akan saling menimpa field
(mis. Sales menambah `email_sent`, Support menghapus `score`). `update` hanya menambah.

**Jangan** memakai `SharedContext` sebagai message queue. Ia menyimpan fakta, bukan perintah.
Perintah antar agent = trigger lewat Orchestrator.

---

## 2. Envelope handoff

Satu key per handoff, isi selalu bentuk yang sama:

```json
{
  "key": "handoff:sales:marketing:lead-42",
  "value": {
    "from": "Sales",
    "to": "Marketing",
    "reason": "lead_converted",
    "subject": "lead:42",
    "payload": { "name": "Budi", "email": "budi@example.com", "score": 0.87, "plan": "premium" },
    "expects": "welcome_email_campaign",
    "deadline": 1731763200,
    "created_at": 1731676800
  }
}
```

| Field | Wajib | Arti |
| --- | --- | --- |
| `from` / `to` | ya | role key persis (AGENTS.md) |
| `reason` | ya | enum pendek, dipakai untuk routing & metrik |
| `subject` | ya | key context sumber (`lead:42`, `ticket:t-9`, `episode:e-7`) |
| `payload` | ya | data minimal yang dibutuhkan penerima (bukan dump semua) |
| `expects` | ya | apa yang diharapkan penerima lakukan |
| `deadline` | tidak | epoch detik; lewat ini → Orchestrator eskalasi |
| `created_at` | ya | diisi helper |

Helper supaya bentuknya tidak pernah menyimpang:

```python
# hermes_bridge/handoff.py
import time
from hermes_bridge.shared_context import SharedContext

ctx = SharedContext()

def hand_off(from_role: str, to_role: str, reason: str, subject: str,
             payload: dict, expects: str, deadline: float | None = None) -> str:
    key = f"handoff:{from_role.lower()}:{to_role.lower()}:{subject.split(':')[1]}"
    ctx.set(key, {
        "from": from_role, "to": to_role, "reason": reason, "subject": subject,
        "payload": payload, "expects": expects, "deadline": deadline,
        "created_at": time.time(),
    }, owner=from_role)
    return key

def take(key: str, owner: str) -> dict | None:
    """Ambil handoff, lalu hapus — satu handoff hanya untuk satu penerima."""
    data = ctx.get(key)
    if data and data.get("to") == owner:
        ctx.delete(key)
        return data
    return None
```

`take()` menghapus setelah dibaca: handoff itu **transisi**, bukan state. Kalau penerima butuh
datanya lagi, ia menulis context miliknya sendiri (`lead:42` tetap ada).

---

## 3. Tabel handoff resmi

Hanya transisi di bawah ini yang diizinkan. Selain itu = desain baru, harus punya baris di tabel
sebelum masuk kode.

| Dari | Ke | Reason | Payload minimal | Expects |
| --- | --- | --- | --- | --- |
| Sales | Marketing | `lead_converted` | nama, email, skor, plan | `welcome_email_campaign` |
| Sales | Support | `meeting_scheduled` | waktu, zona, kebutuhan khusus | `pre_meeting_brief` |
| Marketing | Support | `customer_onboarding` | plan, channel akuisisi | `onboarding_followup` |
| Support | Orchestrator | `ticket_unresolved` | alasan, 3 pesan terakhir | `escalate_to_human` |
| UserReportAgent | Support | `report_account` | kategori, deskripsi, user_id | `handle_billing` |
| UserReportAgent | QualityChecker | `report_technical` | episode_id, jenis masalah | `recheck_episode` |
| PaymentAgent | RevenueTracker | `payment_settled` | order_id, amount, method | `record_transaction` |
| PaymentAgent | SecOps | `chargeback` | order_id, user_id, alasan | `flag_account` |
| DMCA | EpisodeScheduler | `takedown` | episode_id / anime_id, rentang | `cancel_schedule` |
| Scraper | Metadata | `episode_fetched` | episode_id, source | `enrich_metadata` |
| QualityChecker | Orchestrator | `qc_failed` | episode_id, jenis kerusakan, attempt | `retry_or_escalate` |
| Orchestrator | Manusia | `escalate` | ringkasan, opsi keputusan | `decide` |

---

## 4. Contoh lengkap: Sales → Marketing

```python
# hermes_bridge/agents/sales.py (bagian akhir run_sync)
from hermes_bridge.handoff import hand_off
from hermes_bridge import bridge

def _on_qualified(aid: str, lead: dict) -> None:
    bridge.agent_update(aid, "Menyimpan lead & menyiapkan handoff...", tool="update_crm")
    ctx.update(f"lead:{lead['id']}", {"status": "qualified", "score": lead["score"]},
               owner="Sales")
    hand_off(
        from_role="Sales", to_role="Marketing", reason="lead_converted",
        subject=f"lead:{lead['id']}",
        payload={"name": lead["name"], "email": lead["email"],
                 "score": lead["score"], "plan": lead.get("plan", "premium")},
        expects="welcome_email_campaign",
        deadline=time.time() + 3600,
    )
    bridge.update_biz_metrics({"leads_qualified": 1})
    bridge.agent_done(aid, "Lead qualified → Marketing ✓")
```

Penerima mengambilnya saat dijalankan, bukan dengan polling:

```python
# hermes_bridge/agents/marketing.py
from hermes_bridge.handoff import take

def run_sync(self, data: dict) -> str:
    aid = bridge.agent_start("Marketing", "Marketing", "Menjalankan campaign")
    handoff = take(f"handoff:sales:marketing:{data['lead_id']}", owner="Marketing")
    lead = handoff["payload"] if handoff else ctx.get(f"lead:{data['lead_id']}")
    ...
```

Kalau `handoff` tidak ada dan context juga tidak ada: **jangan** mengarang lead. Kirim
`agent_error(aid, "Context lead hilang", retrying=False)` — itu tanda ada bug handoff.

---

## 5. Aturan yang mengikat

1. **Satu handoff, satu penerima.** `take()` menghapus. Kalau butuh broadcast, tulis context
   `subject`, bukan handoff.
2. **Payload minimal.** Kalau penerima butuh lebih, ia membaca `subject` di context. Menyalin
   seluruh percakapan ke payload adalah cara termudah membuat DB membengkak.
3. **Tidak ada import antar agent.** `sales.py` tidak boleh `from .marketing import ...`.
   Yang boleh: `bridge`, `db`, `shared_context`, `handoff`, `kb`.
4. **Tidak ada handoff balik diam-diam.** Kalau Marketing ingin memberi tahu Sales, itu handoff
   baru dengan baris baru di tabel §3.
5. **Timeout = eskalasi.** Orchestrator memeriksa `deadline` (job `check_handoffs`, SCHEDULER.md);
   yang lewat → `escalate_to_human`.
6. **Owner selalu role key**, bukan nama tampilan. `owner="Sales"`, bukan `"Sales Agent"`.
7. **Bersihkan.** Context 24 jam; handoff yang tidak diambil ikut terhapus oleh cleanup 03.00.
   Handoff yang hilang karena cleanup = ada agent yang tidak pernah jalan; itu masalah orkestrasi,
   bukan masalah context.

---

## 6. Anti-pattern (pernah terjadi di rancangan awal)

| Anti-pattern | Kenapa salah | Gantinya |
| --- | --- | --- |
| `run_orchestrator()` dipanggil dari agent untuk "menitip" kerja | Orchestrator jadi re-entrant, dua karakter, routing ganda | `hand_off()` + trigger baru |
| Menyimpan seluruh state LangGraph di context | DB membengkak, schema bocor | simpan `subject` + payload minimal |
| `SharedContext` tanpa lock | `sqlite3` dari banyak thread = `database is locked` | lock di semua method (sudah) |
| Cleanup dihapus karena "context hilang" | DB tumbuh tanpa batas | perbaiki deadline/agent, jangan cleanup |
| Handoff dibaca dua kali (tanpa `take`) | dua agent mengerjakan hal sama | `take()` one-shot |

---

## 7. Checklist uji

- [ ] Dua thread menulis key sama dengan `update()` → tidak ada field hilang
- [ ] `take()` kedua mengembalikan `None`
- [ ] Handoff lewat `deadline` memicu eskalasi (bukan menggantung)
- [ ] Cleanup 24 jam menghapus context lama dan **tidak** menghapus yang baru
- [ ] Sales → Marketing → Support berantai: tiga karakter muncul berurutan, `handoff:*` kosong lagi
- [ ] Tidak ada `import` antar file di `hermes_bridge/agents/` (cek `grep -r "from \." agents/`)
