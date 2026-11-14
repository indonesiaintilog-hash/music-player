# Music Player (Spotify-style)

Aplikasi web pemutar musik bertema gelap seperti Spotify, dibangun dengan **Python + Flask**.

Tersedia **dua sumber musik** (tombol **Preview / Full** di kanan atas):

| Sumber | Katalog | Durasi | Butuh API key |
|--------|---------|--------|---------------|
| **Preview** | iTunes / Apple Music | 30 detik | Tidak |
| **Full** | Audius (artis indie) | **Lagu penuh** | Tidak |

> Catatan: katalog mainstream (Spotify/Apple) **tidak** bisa diputar penuh secara gratis —
> Spotify Web Playback SDK hanya streaming untuk akun **Premium** pengguna, dan Apple Music
> butuh Apple Developer + pelanggan. Untuk lagu penuh gratis & legal, gunakan sumber **Full (Audius)**.

> **AI Covers:** bagian 🤖 AI Covers menampilkan lagu asli yang di-cover/remix AI dari katalog
> yang tersedia (Audius/iTunes). **AI Cover lagu Indonesia belum tersedia** di sumber gratis yang
> bisa diputar langsung; aplikasi menyediakan tautan pencarian ke YouTube untuk itu.

## Fitur

- 🎨 Tampilan ala Spotify (sidebar, kartu ber-cover, player bar di bawah)
- 🔀 Tombol **Preview / Full** untuk berpindah sumber musik
- 🔍 Pencarian nyata: artis, judul lagu, atau album
- 🔥 Tab Trending: **Trending Global** + **🇮🇩 Trending Indonesia** + **🤖 AI Covers**
- ⚙️ **Pengaturan**: Equalizer (6-band + preset) dan pemutar **musik lokal**
- ❤️ Favorites (disimpan di browser via localStorage)
- ▶️ Player lengkap: play/pause, next/prev, progress bar (bisa di-seek), volume
- ⌨️ Shortcut: Space untuk Play/Pause
- 📱 Responsif untuk layar kecil

## Instalasi

```bash
pip install -r requirements.txt
```

## Menjalankan

```bash
cd C:\Music_Online
python music_player.py
```

Buka browser: **http://localhost:5001**

## Cara Pakai

1. **Cari musik** - ketik nama artis/lagu/album di kolom atas, tekan Enter atau tombol "Cari".
2. **Putar** - klik kartu lagu atau tombol ▶ yang muncul saat hover.
3. **Favorit** - klik ikon ❤ pada kartu; lihat di menu **Favorites**.
4. **Trending** - buka menu **Trending** untuk lagu-lagu populer.
5. **Kontrol** - gunakan player bar di bawah: seek, volume, next/prev, play/pause.
6. **Pengaturan** (menu ⚙️):
   - **Equalizer**: aktifkan, pilih preset (Flat/Bass/Treble/Vocal/Rock/Pop/Jazz), atau geser 6 band (60Hz–10kHz).
   - **Musik Lokal**: pilih file audio dari komputer (MP3/WAV/OGG/M4A/FLAC) lalu klik untuk memutar.

## Teknologi

- **Python 3.x**
- **Flask** - web server & proxy API
- **Requests** - memanggil iTunes Search API

## Endpoint API

| Endpoint | Keterangan |
|----------|------------|
| `GET /api/search?q=<kata>` | Cari lagu/artis/album di iTunes (preview 30 dtk) |
| `GET /api/trending` | Trending dari iTunes |
| `GET /api/audius/search?q=<kata>` | Cari lagu **penuh** di Audius |
| `GET /api/audius/trending` | Trending lagu **penuh** dari Audius |

## Opsi lagu penuh (full track) gratis

1. **Audius** - sudah terintegrasi (tombol **Full**). API publik, tanpa key, lagu penuh.
   Katalog berisi artis indie/elektronik/hip-hop, bukan artis mainstream.
2. **Jamendo** - musik Creative Commons, butuh client_id gratis (registrasi).
3. **Internet Archive** - audio domain publik / CC.
4. **Spotify Web Playback SDK** - gratis untuk developer, tetapi pengguna akhir harus punya
   akun Spotify **Premium**; butuh OAuth app.
5. **Apple MusicKit** - butuh Apple Developer (berbayar) + pengguna berlangganan.

Untuk memutar lagu mainstream secara penuh tanpa batasan, satu-satunya cara legal adalah
menggunakan layanan berlangganan (Spotify/Apple Music) melalui API resmi mereka.

## License

MIT License
