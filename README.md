# Teneo Agent Bot — CLI

Auto-run Agent requests untuk quest points (25–100 requests → up to 350,000 pts).

## Setup (1x)

```bash
# 1. Install dependencies
pip install websockets aiohttp colorama python-dotenv

# 2. Buat file .env
cp .env.example .env

# 3. Isi session key kamu di .env
#    TENEO_SESSION_KEY=xxx
#    Dapatkan dari: https://agent-console.ai → Create Session Key
```

## Jalankan

```bash
# Default (50 requests)
python teneo_bot.py

# Target 100 requests
python teneo_bot.py --requests 100

# Lebih lambat (delay 3 detik antar request)
python teneo_bot.py --requests 100 --delay 3

# Via env variable langsung (tanpa .env file)
TENEO_SESSION_KEY=abc123 python teneo_bot.py --requests 25
```

## Alur kerja bot

```
1. Baca SESSION_KEY dari .env
2. Auto-discover agent yang tersedia
3. Kirim request satu per satu dengan jeda + random jitter
4. Tampilkan progress bar + poin earned di terminal
5. Print summary setelah selesai
```

## Catatan

- Pastikan wallet sudah di-link di Dashboard sebelum jalan
- Session Key harus sudah dibuat di Agent Console
- Tekan Ctrl+C kapan saja untuk berhenti (summary tetap tampil)
- Jika banyak error, cek Session Key kamu masih valid
