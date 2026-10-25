import asyncio
import json
import os
import queue
import re
import socket
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

KLASOR = Path(__file__).parent
if sys.stdout is None:  # pythonw ile penceresiz çalışıyorsa çıktıyı dosyaya yaz
    sys.stdout = sys.stderr = open(KLASOR / "bot.log", "a", encoding="utf-8", buffering=1)

# Aynı anda iki bot çalışıp her mesajı iki kez okumasın
_kilit = socket.socket()
try:
    _kilit.bind(("127.0.0.1", 47291))
except OSError:
    raise SystemExit("Bot zaten çalışıyor.")

import aiohttp
import certifi
import discord
import miniaudio
from discord import app_commands
from dotenv import load_dotenv
from edge_tts.communicate import DRM, SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL, date_to_string

load_dotenv(KLASOR / ".env")
TOKEN = os.getenv("DISCORD_TOKEN")
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY")
# /mode komutundaki seçenekler: ad -> ElevenLabs modeli. İlki varsayılan.
ELEVEN_MODLAR = {
    "Duygulu (v3)": "eleven_v3",  # sitedeki gibi duygulu, ilk ses ~0.8 sn, 2 kat kredi
    "Hızlı (Flash)": "eleven_flash_v2_5",  # düz ama ilk ses ~0.2 sn
}
# /voice komutunda çıkan ElevenLabs sesleri: ad -> voice_id. Türkçe ses eklemek için buraya satır ekle.
ELEVEN_SESLER = {
    "Sarah (kadın)": "EXAVITQu4vr4xnSDxMaL",
    "George (erkek)": "JBFqnCBsd6RMkjVDRZzb",
    "Anıl": "KxYUuDOuV6OvSseupTEh",
    "Nygma": "8hS2NaV5RsaEqrmomWSw",  # kütüphane sesi: ücretli plan gerektirir
    "Şevki": "MoAl27wTQMGQ63UoHoKO",
    "Ciddi": "GHsmpPAsGBbipEab9fS1",
}
EMEL = "Emel (Microsoft, bedava)"
VARSAYILAN_SES = next(iter(ELEVEN_SESLER)) if ELEVEN_KEY else EMEL
SES = "tr-TR-EmelNeural"
GOOGLE_URL = "https://translate.google.com/translate_tts"
MAX_UZUNLUK = 1000  # bir mesajdan okunacak en fazla karakter (uzun mesajlar ElevenLabs kredisini hızlı bitirir)
GOOGLE_UZUNLUK = 200  # Google (son yedek) tek seferde en fazla 200 karakter okuyor
ELEVEN_AYNI_ANDA = 3  # ElevenLabs aynı anda istek sınırı: ücretsiz 2, Starter 3
ELEVEN_UZUNLUK = 300  # bundan uzun mesajlar kredi harcamasın diye Emel'le okunur
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002300-\U000023FF\U00002B00-\U00002BFF"
    "\U0000FE0F\U0000200D\U000020E3\U00003030\U0000303D\U00003297\U00003299]+"
)
YEDEK_OMRU = 20  # Microsoft boşta bekleyen bağlantıyı 25-60 sn arasında kapatıyor
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
KARSILAMA = "Selam, ben kişisel asistanınız. Bugün size nasıl yardımcı olabilirim?"
# Bu kişiler ne yazarsa yazsın mesajları yerine bu cümle okunur (kullanıcı id -> cümle). Kaldırmak için satırı sil.
SABIT_CUMLELER = {
    508269383282327552: "ben berke ben bir malım konuşmayı bilmiyorum",
}
EDGE_AYAR = (
    "Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n"
    '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false",'
    '"wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n'
)


def mesaj_izni_acik_mi() -> bool:
    # Developer Portal'da "Message Content Intent" açık mı? Kapalıyken istersek Discord bağlantıyı reddediyor.
    req = urllib.request.Request(
        "https://discord.com/api/v10/applications/@me",
        headers={"Authorization": f"Bot {TOKEN}", "User-Agent": "DiscordBot (tts-bot, 1)"},
    )
    flags = json.load(urllib.request.urlopen(req))["flags"]
    return bool(flags & (1 << 18 | 1 << 19))


intents = discord.Intents.default()
intents.message_content = bool(TOKEN) and mesaj_izni_acik_mi()
if not intents.message_content:
    print("UYARI: Message Content Intent kapalı, yazılanları okuyamam. Portal'dan açıp kaydet, botu yeniden başlat.")
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
http: aiohttp.ClientSession

okuma_kanali: dict[int, int] = {}  # sunucu id -> okunacak yazı kanalı id
kuyruklar: dict[int, asyncio.Queue] = {}  # sunucu başına sırayla okumak için
ses_secimi: dict[int, str] = {}  # sunucu id -> /voice ile seçilen ses adı
mod_secimi: dict[int, str] = {}  # sunucu id -> /mode ile seçilen ElevenLabs modeli
KISI_SESLERI_DOSYASI = KLASOR / "kisi_sesleri.json"
try:  # kullanıcı id -> /myvoice ile seçtiği ses; bot yeniden başlasa da kalsın diye dosyada
    kisi_sesleri: dict[int, str] = {int(k): v for k, v in json.loads(KISI_SESLERI_DOSYASI.read_text("utf-8")).items()}
except (OSError, ValueError):
    kisi_sesleri = {}
eleven_kapali_kadar = 0.0  # kredi biterse ElevenLabs bir süre denenmesin
eleven_sira = asyncio.Semaphore(ELEVEN_AYNI_ANDA)


def temizle(metin: str) -> str:
    metin = re.sub(r"https?://\S+", "link geldi", metin)
    metin = re.sub(r"<a?:\w+:\d+>", " ", metin)  # sunucunun özel emojileri
    metin = EMOJI.sub(" ", metin)  # normal emojiler
    metin = re.sub(r"\s+", " ", metin)
    return kirp(metin.strip(), MAX_UZUNLUK)


def kirp(metin: str, uzunluk: int) -> str:
    # Sınırı aşarsa kelimenin ortasında değil, son boşlukta kes
    if len(metin) <= uzunluk:
        return metin
    return metin[:uzunluk].rsplit(" ", 1)[0]


async def edge_baglan() -> aiohttp.ClientWebSocketResponse:
    return await http.ws_connect(
        f"{WSS_URL}&ConnectionId={uuid.uuid4().hex}&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
        f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
        compress=15,
        headers=DRM.headers_with_muid(WSS_HEADERS),
        ssl=SSL_CTX,
    )


async def kapat(gorev: asyncio.Task):
    try:
        await (await gorev).close()
    except Exception:
        pass


class EdgeYedek:
    # Microsoft'a bağlanmak ~0.8 sn sürüyor: bir bağlantıyı önceden açık tutup mesaj gelince hazır kullanıyoruz
    def __init__(self):
        self.gorev: asyncio.Task | None = None
        self.acilis = 0.0

    def tazele(self):
        if self.gorev:
            asyncio.create_task(kapat(self.gorev))
        self.gorev = asyncio.create_task(edge_baglan())
        self.acilis = time.monotonic()

    def bayat(self) -> bool:
        return self.gorev is None or time.monotonic() - self.acilis > YEDEK_OMRU

    def birak(self):
        if self.gorev:
            asyncio.create_task(kapat(self.gorev))
        self.gorev = None

    async def al(self) -> aiohttp.ClientWebSocketResponse:
        if self.bayat():
            self.tazele()
        gorev, self.gorev = self.gorev, None
        self.tazele()  # sıradaki mesaj için yenisini hemen aç
        return await gorev


yedek = EdgeYedek()


async def yedegi_sicak_tut():
    tur = 0
    while True:
        await asyncio.sleep(2)
        tur += 1
        if not client.voice_clients:
            yedek.birak()
            continue
        if yedek.bayat():
            yedek.tazele()
        if ELEVEN_KEY and tur % 5 == 0:
            # ElevenLabs'a bağlantıyı açık tut; yoksa ilk mesajda bağlanmak ~1 sn ekliyor (ücretsiz istek)
            try:
                async with http.head("https://api.elevenlabs.io/"):
                    pass
            except Exception:
                pass


class ParcaKaynagi(miniaudio.StreamableSource):
    # Ağdan parça parça gelen mp3. Discord'un ses thread'i okurken veri gelmediyse gelene kadar bekler.
    def __init__(self):
        self.kuyruk: queue.Queue[bytes | None] = queue.Queue()
        self.tampon = b""
        self.bitti = False
        self.geldi = False
        self.ilk_parca = asyncio.Event()

    def ekle(self, veri: bytes | None):
        if veri:
            self.geldi = True
            self.ilk_parca.set()
        self.kuyruk.put(veri)

    def read(self, n: int) -> bytes:
        while not self.tampon and not self.bitti:
            parca = self.kuyruk.get()
            if parca is None:
                self.bitti = True
            else:
                self.tampon += parca
        cikti, self.tampon = self.tampon[:n], self.tampon[n:]
        return cikti


class AkisSesi(discord.AudioSource):
    # mp3'ü geldikçe Discord'un istediği 20 ms'lik 48 kHz stereo PCM parçalara çözer
    CERCEVE = 3840

    def __init__(self, kaynak: ParcaKaynagi):
        self.kaynak = kaynak
        self.akis = None
        self.tampon = b""

    def read(self) -> bytes:
        if self.akis is None:
            # Çözücü açılırken veri bekliyor; bu yüzden event loop'ta değil burada (ses thread'inde) açılmalı
            self.akis = miniaudio.stream_any(
                self.kaynak,
                source_format=miniaudio.FileFormat.MP3,
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=2,
                sample_rate=48000,
                frames_to_read=960,
            )
        while len(self.tampon) < self.CERCEVE:
            parca = next(self.akis, None)
            if parca is None:
                if not self.tampon:
                    return b""
                self.tampon = self.tampon.ljust(self.CERCEVE, b"\0")
                break
            self.tampon += parca.tobytes()
        cerceve, self.tampon = self.tampon[: self.CERCEVE], self.tampon[self.CERCEVE :]
        return cerceve


async def edge_akit(metin: str, kaynak: ParcaKaynagi):
    ws = await yedek.al()
    try:
        ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='tr-TR'><voice name='{SES}'>"
            f"<prosody pitch='+0Hz' rate='+0%' volume='+0%'>{escape(metin)}</prosody></voice></speak>"
        )
        await ws.send_str(f"X-Timestamp:{date_to_string()}\r\n{EDGE_AYAR}")
        await ws.send_str(
            f"X-RequestId:{uuid.uuid4().hex}\r\nContent-Type:application/ssml+xml\r\n"
            f"X-Timestamp:{date_to_string()}Z\r\nPath:ssml\r\n\r\n{ssml}"
        )
        async for m in ws:
            if m.type == aiohttp.WSMsgType.TEXT and "Path:turn.end" in m.data:
                break
            if m.type == aiohttp.WSMsgType.BINARY:
                baslik = int.from_bytes(m.data[:2], "big")
                kaynak.ekle(m.data[baslik + 2 :])
        if not kaynak.geldi:
            raise RuntimeError(f"Edge ses göndermedi (kod {ws.close_code})")
    finally:
        await ws.close()


async def eleven_akit(metin: str, voice_id: str, model: str, kaynak: ParcaKaynagi):
    global eleven_kapali_kadar
    async with eleven_sira, http.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": ELEVEN_KEY},
        json={"text": metin, "model_id": model, "language_code": "tr"},
    ) as r:
        if r.status != 200:
            hata = (await r.text())[:300]
            if r.status in (401, 402):  # kredi bitti / anahtar geçersiz: 10 dk Emel ile devam et
                eleven_kapali_kadar = time.monotonic() + 600
            raise RuntimeError(f"ElevenLabs {r.status}: {hata}")
        async for parca in r.content.iter_any():
            kaynak.ekle(parca)


async def google_akit(metin: str, kaynak: ParcaKaynagi):
    params = {"ie": "UTF-8", "q": kirp(metin, GOOGLE_UZUNLUK), "tl": "tr", "client": "tw-ob"}
    async with http.get(GOOGLE_URL, params=params) as r:
        r.raise_for_status()
        kaynak.ekle(await r.read())


async def ses_uret(metin: str, ses: str, model: str, kaynak: ParcaKaynagi):
    # Seçilen ses olmazsa sıradakine geç: ElevenLabs -> Emel (Microsoft) -> Google
    denemeler = []
    kisa = len(metin) <= ELEVEN_UZUNLUK
    if ses in ELEVEN_SESLER and ELEVEN_KEY and kisa and time.monotonic() > eleven_kapali_kadar:
        denemeler.append(("ElevenLabs", eleven_akit(metin, ELEVEN_SESLER[ses], model, kaynak)))
    denemeler += [("Edge", edge_akit(metin, kaynak)), ("Google", google_akit(metin, kaynak))]
    try:
        for i, (ad, deneme) in enumerate(denemeler):
            try:
                # İlk ses 10 sn içinde gelmezse sıradakine geç; geldiyse uzun metnin bitmesini bekle
                gorev = asyncio.ensure_future(deneme)
                ilk = asyncio.ensure_future(kaynak.ilk_parca.wait())
                await asyncio.wait({gorev, ilk}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                ilk.cancel()
                if not kaynak.geldi and not gorev.done():
                    gorev.cancel()
                    raise TimeoutError("10 sn içinde ses gelmedi")
                await asyncio.wait_for(gorev, 120)
                if kaynak.geldi:
                    break
                raise RuntimeError("ses gelmedi")
            except Exception as e:
                if kaynak.geldi:
                    print(f"{ad} yarıda kesildi: {e!r}")
                    break
                print(f"{ad} olmadı, sıradakine geçiliyor: {e!r}")
        for _, kalan in denemeler[i + 1 :]:
            kalan.close()  # başlatılmayan denemeler "never awaited" uyarısı vermesin
    finally:
        kaynak.ekle(None)


def seslendir(guild: discord.Guild, metin: str, kisi_id: int | None = None):
    metin = temizle(metin)
    if not metin:
        return
    # Ses hemen üretilmeye başlar (önceki mesaj çalarken bile), çalma sırası korunur
    kaynak = ParcaKaynagi()
    # Önce kişinin kendi sesi, yoksa sunucunun /voice ile seçtiği ses
    ses = kisi_sesleri.get(kisi_id) or ses_secimi.get(guild.id, VARSAYILAN_SES)
    if ses not in ELEVEN_SESLER and ses != EMEL:  # listeden kaldırılmış bir ses kaydı kalmışsa
        ses = ses_secimi.get(guild.id, VARSAYILAN_SES)
    model = ELEVEN_MODLAR[mod_secimi.get(guild.id, next(iter(ELEVEN_MODLAR)))]
    asyncio.create_task(ses_uret(metin, ses, model, kaynak))
    if guild.id not in kuyruklar:
        kuyruklar[guild.id] = asyncio.Queue()
        asyncio.create_task(oynatici(guild, kuyruklar[guild.id]))
    kuyruklar[guild.id].put_nowait(kaynak)


async def oynatici(guild: discord.Guild, kuyruk: asyncio.Queue):
    while True:
        kaynak = await kuyruk.get()
        try:
            vc = guild.voice_client
            if not vc or not vc.is_connected():
                continue
            bitti = asyncio.Event()
            vc.play(AkisSesi(kaynak), after=lambda _: client.loop.call_soon_threadsafe(bitti.set))
            await bitti.wait()
        except Exception as e:
            print(f"Seslendirme hatası: {e}")


@client.event
async def setup_hook():
    global http
    http = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"})
    asyncio.create_task(yedegi_sicak_tut())
    await tree.sync()


@client.event
async def on_ready():
    print(f"{client.user} olarak giriş yapıldı.")


@tree.command(name="join", description="Bulunduğun ses kanalına gelir, bu kanaldaki mesajları okur")
async def gel(interaction: discord.Interaction):
    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.response.send_message("Önce bir ses kanalına gir.", ephemeral=True)
    kanal = interaction.user.voice.channel
    if yedek.bayat():
        yedek.tazele()  # ses kanalına bağlanırken Microsoft bağlantısı da hazırlansın
    # Ses bağlantısı Discord'un 3 saniyelik cevap süresini aşabiliyor; önce "düşünüyor..." diye cevap ver
    await interaction.response.defer()
    vc = interaction.guild.voice_client
    try:
        if vc:
            await vc.move_to(kanal)
        else:
            await kanal.connect(timeout=20, reconnect=False)
    except Exception as e:
        print(f"Ses kanalına bağlanamadım: {e!r}")
        return await interaction.followup.send(f"Ses kanalına bağlanamadım: `{e!r}`")
    okuma_kanali[interaction.guild_id] = interaction.channel_id
    await interaction.followup.send(f"**{kanal.name}** kanalındayım, bu kanala yazılanları okuyacağım.")
    seslendir(interaction.guild, KARSILAMA)


@tree.command(name="leave", description="Ses kanalından çıkar")
async def git(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc:
        return await interaction.response.send_message("Zaten bir ses kanalında değilim.", ephemeral=True)
    await vc.disconnect()
    okuma_kanali.pop(interaction.guild_id, None)
    await interaction.response.send_message("Görüşürüz 👋")


@tree.command(name="voice", description="Okuma sesini değiştirir")
@app_commands.choices(ad=[app_commands.Choice(name=ad, value=ad) for ad in [*ELEVEN_SESLER, EMEL]])
async def ses(interaction: discord.Interaction, ad: app_commands.Choice[str]):
    if ad.value in ELEVEN_SESLER and not ELEVEN_KEY:
        return await interaction.response.send_message("ElevenLabs anahtarı tanımlı değil.", ephemeral=True)
    ses_secimi[interaction.guild_id] = ad.value
    await interaction.response.send_message(f"Ses değişti: **{ad.value}**")


SUNUCU_SESI = "Sunucunun sesi (kendi sesimi kaldır)"


@tree.command(name="myvoice", description="Senin mesajların hangi sesle okunsun (sadece senin için)")
@app_commands.choices(ad=[app_commands.Choice(name=ad, value=ad) for ad in [*ELEVEN_SESLER, EMEL, SUNUCU_SESI]])
async def myvoice(interaction: discord.Interaction, ad: app_commands.Choice[str]):
    if ad.value in ELEVEN_SESLER and not ELEVEN_KEY:
        return await interaction.response.send_message("ElevenLabs anahtarı tanımlı değil.", ephemeral=True)
    if ad.value == SUNUCU_SESI:
        kisi_sesleri.pop(interaction.user.id, None)
        cevap = "Artık mesajların sunucunun sesiyle okunacak."
    else:
        kisi_sesleri[interaction.user.id] = ad.value
        cevap = f"{interaction.user.display_name} artık **{ad.value}** sesiyle okunacak."
    try:
        KISI_SESLERI_DOSYASI.write_text(json.dumps(kisi_sesleri, ensure_ascii=False), "utf-8")
    except OSError as e:
        print(f"Kişi sesleri kaydedilemedi: {e!r}")
    await interaction.response.send_message(cevap)


@tree.command(name="mode", description="ElevenLabs okuma modunu değiştirir: duygulu ya da hızlı")
@app_commands.choices(ad=[app_commands.Choice(name=ad, value=ad) for ad in ELEVEN_MODLAR])
async def mode(interaction: discord.Interaction, ad: app_commands.Choice[str]):
    mod_secimi[interaction.guild_id] = ad.value
    await interaction.response.send_message(f"Mod değişti: **{ad.value}**")


@tree.command(name="skip", description="Şu an okunan mesajı keser, sıradakine geçer")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        return await interaction.response.send_message("Şu an bir şey okumuyorum.", ephemeral=True)
    vc.stop()  # oynatıcı "bitti" sanıp kuyruktaki sıradaki mesaja geçer
    await interaction.response.send_message("Geçildi.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    vc = message.guild.voice_client
    if okuma_kanali.get(message.guild.id) == message.channel.id and vc:
        # Sadece botla aynı ses kanalında olanların yazdıkları okunur
        if not message.author.voice or message.author.voice.channel != vc.channel:
            return
        metin = message.clean_content
        if message.attachments:  # resim, video, ses, belge...
            metin = f"{metin} dosya geldi"
        metin = SABIT_CUMLELER.get(message.author.id, metin)
        seslendir(message.guild, metin, message.author.id)


@client.event
async def on_voice_state_update(member, before, after):
    # Kanalda bottan başka kimse kalmadıysa çık
    vc = member.guild.voice_client
    if vc and len([m for m in vc.channel.members if not m.bot]) == 0:
        await vc.disconnect()
        okuma_kanali.pop(member.guild.id, None)


if not TOKEN:
    raise SystemExit(".env dosyasında DISCORD_TOKEN yok.")
client.run(TOKEN)
