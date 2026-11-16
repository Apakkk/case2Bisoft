"""Çıkarım: LLM çağrısı + Pydantic doğrulaması + anlam kontrolü + yeniden deneme.

Şema garantisinin katmanları:
1. Kısıtlı üretim (llama.cpp grammar): biçim üretim sırasında garanti.
2. Pydantic (`extra="forbid"`, tipler, enum'lar): ikinci biçim kontrolü.
3. Anlam kontrolü (aşağıda): her değer mesaj metnine karşı kontrol edilir. Model geçerli biçimde
   yanlış/uydurma bir değer yazabilir; bunu yakalayan katman budur.
4. Tutmazsa hata mesajı prompt'a eklenip 1 kez yeniden denenir; yine tutmazsa kayıt
   "Manuel inceleme"ye düşer (merge.py). "Düşük güven" = hangi kontrolün başarısız olduğu
   (açıklanabilir bayrak), logprob gibi yorumlanması zor bir skor değil.
"""
from __future__ import annotations

import re

from openai import OpenAI
from pydantic import ValidationError

from . import config
from .container import konteyner_bul, normalize_konteyner
from .dates import TarihHatasi, tarih_coz
from .llm import LlmCevap, cagir
from .prompt import mesaj_listesi
from .schema import CikarimSonucu, Mesaj, MesajCikarimi

_IS_GUNU_RE = re.compile(r"business|working|iş gün|is gun|işgün")
# Gate-out kanıtı: konteynerin terminalden çıktığını söyleyen ifadeler. Boşaltma (unloading,
# "boşaltıldı") gate-out DEĞİLDİR; canlı çalıştırmada model M4/M10'da bunu karıştırdı.
_GATE_OUT_RE = re.compile(
    r"gated?[\s-]?out|out[\s-]?gated?|picked up|released|"
    r"(?:left|departed|exited)(?: from)? the (?:terminal|port|yard)|"
    r"(?:terminal|liman|saha)(?:den|dan)? (?:çık|ayrıl)|çıkış(?:ı)? yap|çekildi|teslim alındı")

# Yazıyla yazılmış gün sayıları ("five calendar days", "beş iş günü"). Yalnızca bir gün birimiyle
# birlikte sayılır; böylece İngilizce "on" ya da Türkçe "bir" tek başına sayı sanılmaz.
_SAYI_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15,
            "twenty": 20, "twenty-one": 21, "thirty": 30}
_SAYI_TR = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
            "dokuz": 9, "on": 10, "on dört": 14, "on beş": 15, "yirmi": 20, "yirmi bir": 21, "otuz": 30}


def _sozcuk_re(sozluk: dict[str, int], ara: str, birim: str) -> re.Pattern:
    sozcukler = "|".join(sorted(map(re.escape, sozluk), key=len, reverse=True))
    return re.compile(rf"\b({sozcukler})\s+(?:(?:{ara})\s+)*(?:{birim})")


_SAYI_EN_RE = _sozcuk_re(_SAYI_EN, "calendar|business|working|free|full", r"days?\b")
_SAYI_TR_RE = _sozcuk_re(_SAYI_TR, "iş|is|takvim|serbest", "gün|gun")


class AnlamHatasi(ValueError):
    pass


def _duz(s: str) -> str:
    return " ".join(s.replace("İ", "i").lower().split())


def _sayilar(metin: str) -> set[float]:
    """Mesajda geçen sayılar: rakamla yazılanlar + bir gün birimiyle birlikte yazıyla yazılanlar."""
    sayilar = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", metin)}
    duz = _duz(metin)
    sayilar |= {float(_SAYI_EN[m[1]]) for m in _SAYI_EN_RE.finditer(duz)}
    sayilar |= {float(_SAYI_TR[m[1]]) for m in _SAYI_TR_RE.finditer(duz)}
    return sayilar


def anlam_kontrolu(c: MesajCikarimi, m: Mesaj) -> None:
    metin = _duz(m.metin)
    if _duz(c.kanit) not in metin:
        raise AnlamHatasi(f"kanit '{c.kanit}' mesajda birebir geçmiyor")
    for alan in ("gate_out_ifadesi", "iade_ifadesi"):
        v = getattr(c, alan)
        if v and _duz(v) not in metin:
            raise AnlamHatasi(f"{alan} '{v}' mesajda birebir geçmiyor")

    numaralar = konteyner_bul(m.metin)
    if c.mesaj_tipi == "ilgisiz":
        if numaralar:
            raise AnlamHatasi(f"mesajda konteyner numarası var ({numaralar[0]}) ama 'ilgisiz' denmiş")
    else:
        if not numaralar:
            raise AnlamHatasi("konteyner mesajı denmiş ama mesajda konteyner numarası yok")
        if normalize_konteyner(c.konteyner_no_ham) not in numaralar:
            raise AnlamHatasi(f"konteyner_no_ham '{c.konteyner_no_ham}' mesajdaki numarayla eşleşmiyor")

    sayilar = _sayilar(m.metin)
    for k in c.ucret_kademeleri:
        if k.usd_gunluk not in sayilar:
            raise AnlamHatasi(f"ücret {k.usd_gunluk:g} mesajda geçmiyor")
        if k.gun_sayisi is not None and k.gun_sayisi not in sayilar:
            raise AnlamHatasi(f"kademe gün sayısı {k.gun_sayisi} mesajda geçmiyor")
    if c.serbest_sure_gun is not None and c.serbest_sure_gun not in sayilar:
        raise AnlamHatasi(f"serbest süre {c.serbest_sure_gun} mesajda geçmiyor")
    if c.serbest_sure_tipi == "is_gunu" and not _IS_GUNU_RE.search(metin):
        raise AnlamHatasi("serbest_sure_tipi 'is_gunu' denmiş ama mesajda iş günü ifadesi yok")

    if c.mesaj_tipi == "gate_out_bildirimi":
        if not _GATE_OUT_RE.search(metin):
            raise AnlamHatasi(
                "mesaj_tipi 'gate_out_bildirimi' denmiş ama mesajda gate-out ifadesi yok "
                "(gated out / picked up / released / left the terminal). Unloading (boşaltma) is not gate-out; "
                "a message about returning the container is iade_plani")
        if not c.gate_out_ifadesi:
            raise AnlamHatasi("gate-out mesajı denmiş ama gate_out_ifadesi boş")
    if c.gate_out_ifadesi:
        try:
            tarih_coz(c.gate_out_ifadesi, m.tarih)
        except TarihHatasi:
            raise AnlamHatasi(f"gate_out_ifadesi '{c.gate_out_ifadesi}' bir tarihe çözülemiyor") from None
    if c.iade_kesinligi in ("kesin_tarih", "goreli_gun", "belirsiz") and not c.iade_ifadesi:
        raise AnlamHatasi(f"iade_kesinligi '{c.iade_kesinligi}' ama iade_ifadesi boş")
    if c.iade_kesinligi in ("kesin_tarih", "goreli_gun"):
        try:
            tarih_coz(c.iade_ifadesi, m.tarih, baglam=m.metin)
        except TarihHatasi:
            raise AnlamHatasi(
                f"iade_ifadesi '{c.iade_ifadesi}' cannot be resolved to a date from this message; "
                "if no date is given, use iade_kesinligi 'belirsiz'") from None


def cikar(client: OpenAI, m: Mesaj) -> tuple[CikarimSonucu, list[dict]]:
    """Bir mesajı işler. Dönen ikinci değer, cache'e yazılacak deneme kayıtlarıdır."""
    hata: str | None = None
    hatalar: list[str] = []
    denemeler: list[dict] = []
    toplam_sure = 0.0
    for deneme in range(1, config.DENEME_SAYISI + 1):
        cevap: LlmCevap = cagir(client, mesaj_listesi(m, onceki_hata=hata))
        toplam_sure += cevap.sure_sn
        kayit = {"deneme": deneme, **cevap.dict(), "hata": None}
        try:
            c = MesajCikarimi.model_validate_json(cevap.icerik)
            anlam_kontrolu(c, m)
            denemeler.append(kayit)
            return CikarimSonucu(mesaj=m, cikarim=c, hatalar=hatalar, deneme=deneme,
                                 sure_sn=round(toplam_sure, 2)), denemeler
        except (ValidationError, AnlamHatasi) as e:
            hata = str(e).splitlines()[0] if isinstance(e, ValidationError) else str(e)
            hatalar.append(f"deneme {deneme}: {hata}")
            kayit["hata"] = hata
            denemeler.append(kayit)
    return CikarimSonucu(mesaj=m, cikarim=None, hatalar=hatalar, deneme=config.DENEME_SAYISI,
                         sure_sn=round(toplam_sure, 2)), denemeler
