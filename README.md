# Discord Türkçe TTS Botu

Ses kanalına gelip, çağrıldığı yazı kanalına yazılan mesajları Türkçe sesli okuyan Discord botu.

- `ELEVENLABS_API_KEY` tanımlıysa **ElevenLabs** sesleriyle (Flash v2.5, Türkçe) okur; değilse Microsoft Edge'in **Emel** sesiyle.
- Seçilen ses olmazsa (kredi biterse vs.) sırayla Emel'e, o da olmazsa Google sesine geçer.
- ElevenLabs sesleri `bot.py` içindeki `ELEVEN_SESLER` listesinden gelir; yeni ses için oraya `"Ad": "voice_id"` ekle.
- Yazılan mesaj ~0,3 saniyede okunmaya başlar (bağlantı önceden açık tutulur, ses parça parça çalınır).
- Sadece botla aynı ses kanalında olanların yazdıkları okunur.
- Linkler "link geldi", dosyalar "dosya geldi" diye okunur; emojiler atlanır. Bir mesajdan en fazla 1000 karakter okunur.
- 300 karakterden uzun mesajlar ElevenLabs kredisi harcamasın diye Emel'le okunur.
- Kanalda kimse kalmayınca bot kendiliğinden çıkar.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/join` | Bulunduğun ses kanalına gelir, komutu yazdığın kanala yazılanları okur |
| `/leave` | Ses kanalından çıkar |
| `/voice` | Okuma sesini değiştirir |
| `/mode` | ElevenLabs modunu seçer: Duygulu (v3, varsayılan) ya da Hızlı (Flash) |
| `/skip` | Şu an okunan mesajı keser, sıradakine geçer |

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
