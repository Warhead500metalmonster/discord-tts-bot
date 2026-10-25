# Discord Türkçe TTS Botu

Ses kanalına gelip, çağrıldığı yazı kanalına yazılan mesajları Türkçe sesli okuyan Discord botu.

- `ELEVENLABS_API_KEY` tanımlıysa **ElevenLabs** sesleriyle (Flash v2.5, Türkçe) okur; değilse Microsoft Edge'in **Emel** sesiyle.
- Seçilen ses olmazsa (kredi biterse vs.) sırayla Emel'e, o da olmazsa Google sesine geçer.
- ElevenLabs sesleri `bot.py` içindeki `ELEVEN_SESLER` listesinden gelir; yeni ses için oraya `"Ad": "voice_id"` ekle.
- Yazılan mesaj ~0,3 saniyede okunmaya başlar (bağlantı önceden açık tutulur, ses parça parça çalınır).
- Linkler "link" diye, özel emojiler adıyla okunur. En fazla 200 karakter okunur.
- Kanalda kimse kalmayınca bot kendiliğinden çıkar.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/join` | Bulunduğun ses kanalına gelir, komutu yazdığın kanala yazılanları okur |
| `/leave` | Ses kanalından çıkar |
| `/voice` | Okuma sesini değiştirir |

## Kurulum (Windows)

1. Python 3.12 kur.
2. Klasörde:
   ```bash
   python -m venv .venv
   ```
   ```bash
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. `.env.example` dosyasını `.env` olarak kopyala ve bot token'ını yaz.
4. [Discord Developer Portal](https://discord.com/developers/applications) → uygulaman → **Bot** sekmesinde **Message Content Intent**'i aç ve **Save Changes**'a bas.
5. Botu sunucuna ekle (`CLIENT_ID` yerine uygulama ID'sini yaz):
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=3214336`
6. `baslat.bat`'a çift tıkla.

Penceresiz çalıştırmak için `.venv\Scripts\pythonw.exe bot.py` kullan; çıktılar `bot.log` dosyasına yazılır. Bot aynı anda iki kez açılmaz.
