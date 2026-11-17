# AniWatch — FAQ Support (KB)

Satu blok `##` = satu artikel. Baris `category:` dan `tags:` dibaca oleh
`kb.parse_markdown`; sisanya jadi `body`. `id` diambil dari judul, jadi judul
adalah kuncinya — ubah judul, ubah id. Minimal 20 artikel (PLAN.md W5).

## Tidak bisa login ke akun

category: account
tags: login akun masuk password

Pastikan email dan password diketik tanpa spasi di ujung. Kalau lupa password,
pakai "Lupa password" di halaman masuk: tautannya berlaku 30 menit dan hanya
sekali pakai. Kalau email reset tidak datang, cek folder spam lalu coba lagi
setelah 10 menit — permintaan berulang membatalkan tautan sebelumnya.

## Akun terkunci setelah salah password berulang

category: account
tags: akun terkunci lock brute force

Lima percobaan gagal dalam 15 menit mengunci akun sementara selama 15 menit.
Tunggu, lalu masuk lagi — jangan mengulang terus, karena setiap percobaan baru
memperpanjang kunci. Kalau tetap terkunci setelah 30 menit, hubungi support
dengan email akun dan waktu kejadian.

## Cara mengubah email akun

category: account
tags: email akun ganti ubah

Buka Pengaturan → Akun → Ubah email. Kami mengirim tautan konfirmasi ke email
baru dan pemberitahuan ke email lama; keduanya harus dibuka dalam 24 jam.
Setelah itu masuk memakai email baru — password tidak berubah.

## Langganan premium tidak aktif setelah bayar

category: account
tags: premium langganan bayar pembayaran aktif

Aktivasi biasanya selesai di bawah satu menit setelah pembayaran berhasil.
Kalau status masih gratis, muat ulang halaman lalu keluar-masuk sekali. Bila
masih belum aktif setelah 10 menit, kirim ID pesanan (format AW-xxxx) ke
support — kami cocokkan dengan catatan pembayaran, bukan dengan tangkapan layar.

## Pembayaran gagal padahal saldo cukup

category: account
tags: pembayaran gagal kartu saldo

Penyebab paling sering: kartu belum mengizinkan transaksi berulang, atau bank
menolak transaksi kecil untuk verifikasi. Coba metode lain (virtual account
atau e-wallet). Kalau kartu tetap ditolak, hubungi bank — kami tidak menerima
kode penolakan dari pihak bank.

## Cara membatalkan langganan

category: account
tags: langganan batal berhenti perpanjangan

Buka Pengaturan → Langganan → Batalkan perpanjangan. Akses premium tetap
berjalan sampai akhir periode yang sudah dibayar, lalu akun kembali ke gratis
tanpa penagihan berikutnya. Menghapus aplikasi tidak membatalkan langganan.

## Minta refund pembayaran

category: account
tags: refund uang kembali pembayaran

Refund bisa diminta dalam 7 hari sejak pembayaran kalau episode premium belum
ditonton lebih dari 3 judul. Kirim ID pesanan dan alasan ke support; keputusan
diberikan maksimal 2 hari kerja, dan dana kembali ke metode pembayaran asal
dalam 5–14 hari kerja tergantung bank.

## Video buffering terus

category: technical
tags: buffering lambat lag video

Coba turunkan kualitas ke 720p di pemutar, lalu uji jaringan: kecepatan stabil
di atas 5 Mbps cukup untuk 1080p. Kalau buffering hanya terjadi di satu episode,
laporkan episode itu; kalau di semua episode, masalahnya di jaringan atau ISP.

## Video tidak bisa diputar (error 404)

category: technical
tags: error 404 tidak bisa putar hilang

Error 404 berarti berkas episode sedang tidak tersedia di server — biasanya
karena proses unggah ulang. Tunggu 10 menit lalu muat ulang; kalau masih 404
setelah satu jam, laporkan lewat tombol "Laporkan Masalah" dengan ID episode.

## Subtitle tidak muncul

category: technical
tags: subtitle tidak muncul teks

Aktifkan subtitle lewat ikon CC di pemutar dan pilih bahasa Indonesia. Kalau
daftar bahasa kosong, subtitle episode itu belum tersedia — bukan masalah di
perangkat Anda. Coba juga mematikan mode hemat data.

## Subtitle tidak sinkron dengan suara

category: technical
tags: subtitle sinkron timing geser

Geser sinkronisasi di pemutar (ikon CC → penyesuaian) sebesar 0,5 detik per
ketukan. Kalau seluruh episode bergeser sama jauhnya, itu kesalahan berkas:
laporkan dengan ID episode dan menit pertama yang terlihat salah.

## Kualitas tetap 480p padahal premium

category: technical
tags: kualitas 1080p hd premium

Periksa tiga hal: status premium aktif di Pengaturan, kualitas di pemutar
disetel "Auto" atau 1080p, dan bandwidth minimal 8 Mbps untuk 1080p. Di
perangkat lama, dekoder mungkin membatasi ke 720p — itu batas perangkat.

## Episode baru belum muncul

category: content
tags: episode baru rilis jadwal

Jadwal rilis mengikuti sumber resmi dan biasanya muncul dalam 1–3 jam setelah
tayang. Halaman anime menampilkan jam rilis per episode. Kalau lewat 6 jam dari
jadwal, laporkan — bisa jadi berkasnya belum lolos pemeriksaan kualitas.

## Episode salah judul atau salah nomor

category: content
tags: salah episode nomor judul metadata

Laporkan dengan ID episode dan nomor yang seharusnya. Perbaikan metadata
menyentuh daftar episode sekaligus, jadi biasanya selesai dalam satu batch
pemeriksaan, bukan satu per satu.

## Anime hilang dari daftar

category: content
tags: hilang dmca lisensi takedown

Sebagian judul ditarik karena permintaan pemegang hak atau perubahan lisensi.
Judul yang ditarik tidak bisa dipulihkan lewat support. Kalau Anda yakin itu
kekeliruan, kirim tautan halaman lama untuk kami periksa.

## Tidak bisa menonton di TV atau casting

category: technical
tags: tv casting chromecast airplay

Casting butuh perangkat dan TV di jaringan Wi-Fi yang sama. Kalau tombol cast
tidak menemukan TV, matikan lalu nyalakan ulang layanan cast di TV. Browser
desktop hanya bisa cast lewat Chrome; Safari memakai AirPlay.

## Unduhan tidak tersedia

category: content
tags: unduh download offline

Fitur unduh hanya untuk akun premium dan hanya pada aplikasi resmi. Unduhan
kedaluwarsa setelah 30 hari atau saat langganan berakhir. Kalau tombol unduh
hilang padahal premium, keluar-masuk akun sekali.

## Riwayat tontonan tidak tersimpan

category: technical
tags: riwayat history lanjut nonton

Riwayat disimpan per akun, bukan per perangkat, dan baru tercatat setelah 30
detik pemutaran. Kalau tetap kosong, pastikan tidak memakai mode privat dan
tidak menonton sebagai tamu.

## Notifikasi rilis tidak masuk

category: technical
tags: notifikasi push rilis email

Notifikasi butuh izin dari sistem operasi dan, untuk email, alamat yang sudah
diverifikasi. Aktifkan di Pengaturan → Notifikasi, lalu periksa pengaturan
baterai: sebagian ponsel mematikan notifikasi aplikasi yang jarang dibuka.

## Laporan masalah: apa yang harus disertakan

category: account
tags: laporan report bug laporkan

Sertakan ID episode (atau tautan), waktu kejadian, perangkat dan versi aplikasi,
serta apa yang Anda harapkan terjadi. Untuk masalah akun, cukup email akun dan
ID pesanan — jangan pernah mengirim password atau kode verifikasi.

## Kenapa komentar saya dihapus

category: content
tags: komentar moderator hapus aturan

Komentar dihapus kalau memuat tautan bajakan, ujaran kebencian, atau spoiler
tanpa penanda. Penghapusan disertai alasan di notifikasi. Keberatan bisa
diajukan sekali lewat tombol "Ajukan banding" pada notifikasi tersebut.

## Batas perangkat untuk satu akun

category: account
tags: perangkat batas sesi streaming

Satu akun premium bisa menonton di dua perangkat bersamaan; perangkat ketiga
akan menolak pemutaran sampai salah satu sesi ditutup. Daftar sesi aktif ada di
Pengaturan → Keamanan, lengkap dengan tombol keluar dari jauh.

## Aplikasi menutup sendiri saat membuka episode

category: technical
tags: crash aplikasi tutup error

Biasanya cache pemutar yang rusak. Keluarkan episode itu dari daftar "Lanjut
nonton", hapus cache aplikasi, lalu buka lagi. Kalau masih menutup sendiri,
kirim model perangkat, versi Android/iOS, dan ID episode — itu tiga hal yang
kami butuhkan untuk mereproduksi.
