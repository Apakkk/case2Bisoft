"""Metindeki tarih ifadesini gerçek tarihe çeviren deterministik çözümleyici.

Model tarihleri metinde yazıldığı gibi kopyalar ("28 Sep 2026", "6 Ekim'de", "perşembe");
gerçek tarihe çevirme işi burada, mesaj tarihine (referans) göre yapılır.

Varsayımlar (README'de de yazılı):
- Sayısal tarihler gün/ay sırasıyla okunur (30/09/2026, 8.10): Avrupa/Türkiye biçimi.
- Yıl yazılmamışsa mesajın yılı alınır; sonuç mesaj tarihinden 180 günden fazla gerideyse
  bir sonraki yıl sayılır (Aralık'ta yazılan "5 Ocak" gibi).
- Gün adı ("perşembe") mesaj tarihinden SONRAKİ ilk o güne çözülür. Mesaj perşembe yazılmışsa
  bir sonraki haftanın perşembesi seçilir.
- Tarih ile gün adı birlikte yazılmışsa ("9 Ekim Cuma") tutarlılık kontrol edilir; tutmazsa hata.
- "haftaya bir ara", "en kısa sürede" gibi ifadeler tarih DEĞİLDİR: hata fırlatılır, tahmin edilmez.
- "gelecek hafta" Pazartesi-Pazar takvim haftasına; "haftaya perşembe" o haftanın Perşembesine çözülür.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta


class TarihHatasi(ValueError):
    """İfade kesin bir tarihe çözülemedi (belirsiz, tutarsız ya da tanınmayan biçim)."""


_AYLAR = {
    # İngilizce (önek eşleşir: "sept", "october" da yakalanır)
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # Türkçe (ASCII yazımlarıyla birlikte)
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}

_GUNLER = {  # Python weekday(): Pazartesi=0
    "pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2,
    "perşembe": 3, "persembe": 3, "cumartesi": 5, "cuma": 4, "pazar": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
}

_GORELI = {"bugün": 0, "bugun": 0, "today": 0, "yarın": 1, "yarin": 1, "tomorrow": 1}

# Uzun adlar önce: "cumartesi" "cuma"dan, "pazartesi" "pazar"dan önce denenmeli.
_AY_RE = "|".join(sorted(_AYLAR, key=len, reverse=True))
_GUN_RE = "|".join(sorted(_GUNLER, key=len, reverse=True))
_EK = r"[a-zçğıöşü'’]*"  # Türkçe ek / İngilizce uzun ad: "Ekim'de", "October"

_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_SAYISAL = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_GUN_AY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s.\-]*({_AY_RE}){_EK}\.?(?:[\s,]+(\d{{4}}))?")
_AY_GUN = re.compile(rf"\b({_AY_RE}){_EK}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?")
_GUN_ADI = re.compile(rf"\b({_GUN_RE})")
_GORELI_RE = re.compile(r"\b(" + "|".join(_GORELI) + r")\b")
_HAFTAYA = re.compile(r"\b(?:haftaya|gelecek\s+hafta|next\s+week)\b")


@dataclass(frozen=True)
class TarihCozumu:
    """Orijinal ifade, mesaj referansı, sonuç ve kullanılan deterministik kural."""
    ifade: str
    referans: date
    tarih: date
    kural: str


_GUN_KODU = {"pazartesi": 0, "sali": 1, "carsamba": 2, "persembe": 3, "cuma": 4,
             "cumartesi": 5, "pazar": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
             "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _anahtar(metin: str) -> str:
    s = unicodedata.normalize("NFKD", metin.replace("İ", "i").replace("ı", "i").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _hafta_baslangici(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _adet(s: str) -> int:
    sayilar = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6,
               "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}
    return int(s) if s.isdigit() else sayilar[s]


def tarih_coz_detay(ifade: str, referans: date) -> TarihCozumu:
    """Çözer ve izlenebilir çözüm bilgisini döndürür; belirsizlikte hata verir."""
    s = " ".join(_anahtar(ifade).replace("'", " ").split())
    def sonuc(d: date, kural: str) -> TarihCozumu:
        return TarihCozumu(ifade, referans, d, kural)

    gunler = "|".join(sorted(_GUN_KODU, key=len, reverse=True))
    sabit = {"bugun": (0, "bugün"), "today": (0, "today"), "yarin": (1, "yarın"),
             "tomorrow": (1, "tomorrow"), "obur gun": (2, "öbür gün"),
             "the day after tomorrow": (2, "day after tomorrow"), "dun": (-1, "dün"),
             "yesterday": (-1, "yesterday"), "onceki gun": (-2, "önceki gün"),
             "day before yesterday": (-2, "day before yesterday")}
    if s in sabit:
        n, rule = sabit[s]
        return sonuc(referans + timedelta(days=n), rule)
    m = re.fullmatch(r"(\d+|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on) gun sonra|in (\d+) days?", s)
    if m:
        n = _adet(m[1] or m[2]); return sonuc(referans + timedelta(days=n), f"+{n} gün")
    m = re.fullmatch(r"(\d+|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on) gun once|(\d+) days? ago", s)
    if m:
        n = _adet(m[1] or m[2]); return sonuc(referans - timedelta(days=n), f"-{n} gün")

    if s in ("haftaya bugun", "a week from today"):
        return sonuc(referans + timedelta(days=7), "+7 gün")
    if s == "two weeks from today": return sonuc(referans + timedelta(days=14), "+14 gün")
    if s in ("iki hafta sonra bugun", "two weeks from today"):
        return sonuc(referans + timedelta(days=14), "+14 gün")
    m = re.fullmatch(r"iki hafta sonra (.+)", s)
    if m and m[1] in _GUN_KODU:
        return sonuc(_hafta_baslangici(referans) + timedelta(days=14 + _GUN_KODU[m[1]]), "iki hafta sonrası ISO haftasının günü")

    if s in ("ayin son gunu", "last day of this month"):
        return sonuc(date(referans.year + (referans.month == 12), referans.month % 12 + 1, 1) - timedelta(days=1), "ayın son günü")
    if s == "gelecek ayin 5 i":
        y, mo = (referans.year + 1, 1) if referans.month == 12 else (referans.year, referans.month + 1)
        return sonuc(date(y, mo, 5), "gelecek ayın 5'i")
    if s in ("end of next week", "gelecek haftanin sonu"):
        return sonuc(_hafta_baslangici(referans) + timedelta(days=13), "gelecek ISO haftasının pazarı")
    if s in ("next weekend", "onumuzdeki hafta sonu"):
        return sonuc(_hafta_baslangici(referans) + timedelta(days=12), "gelecek ISO haftasının cumartesisi")

    for prefix in ("bu hafta ", "this "):
        if s.startswith(prefix) and s[len(prefix):] in _GUN_KODU:
            d = _hafta_baslangici(referans) + timedelta(days=_GUN_KODU[s[len(prefix):]])
            return sonuc(d, "bu ISO haftasının günü")
    for prefix in ("haftaya ", "gelecek hafta ", "onumuzdeki hafta ", "next week "):
        if s.startswith(prefix) and s[len(prefix):] in _GUN_KODU:
            d = _hafta_baslangici(referans) + timedelta(days=7 + _GUN_KODU[s[len(prefix):]])
            return sonuc(d, "gelecek ISO haftasının günü")
    m = re.fullmatch(rf"({gunler}) next week", s)
    if m:
        return sonuc(_hafta_baslangici(referans) + timedelta(days=7 + _GUN_KODU[m[1]]), "gelecek ISO haftasının günü")
    m = re.fullmatch(rf"next ({gunler})|onumuzdeki ({gunler})", s)
    if m:
        g = m[1] or m[2]
        return sonuc(_hafta_baslangici(referans) + timedelta(days=7 + _GUN_KODU[g]), "gelecek ISO haftasının günü")
    if s in ("haftaya", "gelecek hafta", "next week", "onumuzdeki hafta"):
        if s != "haftaya":
            return sonuc(_hafta_baslangici(referans) + timedelta(days=7), "gelecek ISO haftasının pazartesi ankrajı")
        raise TarihHatasi(f"'{ifade}' gün belirtmiyor")
    for day in sorted(_GUN_KODU, key=len, reverse=True):
        if s.startswith(day) and s[len(day):] in ("ye", "ya", "e", "a", "de", "da"):
            s = day
            break
    if s in _GUN_KODU:
        n = (_GUN_KODU[s] - referans.weekday()) % 7 or 7
        return sonuc(referans + timedelta(days=n), "sonraki yalın hafta günü")
    raise TarihHatasi(f"'{ifade}' desteklenmiyor veya belirsiz")


def _kucuk(metin: str) -> str:
    # Türkçe "İ" Python'da "i̇" olur; önce düz "i"ye çevir.
    return metin.replace("İ", "i").lower()


def _yil_tamamla(gun: int, ay: int, yil: int | None, referans: date) -> date:
    try:
        if yil is not None:
            if yil < 100:
                yil += 2000
            return date(yil, ay, gun)
        aday = date(referans.year, ay, gun)
    except ValueError as e:
        raise TarihHatasi(f"geçersiz tarih: gün={gun}, ay={ay}, yıl={yil}") from e
    if (referans - aday).days > 180:
        aday = date(referans.year + 1, ay, gun)
    return aday


def _sonraki_gun_adi(hedef: int, referans: date) -> date:
    fark = (hedef - referans.weekday()) % 7
    return referans + timedelta(days=fark or 7)


_AYNI_GUN_RE = re.compile(r"\b(aynı gün|ayni gun|aynı gun|o gün|same day)")


def tarihleri_bul(metin: str, referans: date) -> list[date]:
    """Serbest metindeki açık tarihleri (gün + ay) tekil ve sırayla döner."""
    s, bulunan = _kucuk(metin), []
    for desen, cevir in (
        (_ISO, lambda m: (int(m[3]), int(m[2]), int(m[1]))),
        (_GUN_AY, lambda m: (int(m[1]), _AYLAR[m[2]], int(m[3]) if m[3] else None)),
        (_AY_GUN, lambda m: (int(m[2]), _AYLAR[m[1]], int(m[3]) if m[3] else None)),
        (_SAYISAL, lambda m: (int(m[1]), int(m[2]), int(m[3]) if m[3] else None)),
    ):
        for m in desen.finditer(s):
            try:
                d = _yil_tamamla(*cevir(m), referans)
            except TarihHatasi:
                continue
            if d not in bulunan:
                bulunan.append(d)
    return bulunan


def tarih_coz(ifade: str | None, referans: date, baglam: str | None = None) -> date:
    """İfadeyi `referans` (mesaj tarihi) bağlamında kesin bir tarihe çevirir; olmazsa TarihHatasi.

    "aynı gün" / "same day" bir atıftır: `baglam` (mesajın tam metni) içinde TEK bir açık tarih
    varsa ona çözülür; hiç yoksa ya da birden fazlaysa tahmin edilmez, hata fırlatılır.
    """
    if not ifade or not ifade.strip():
        raise TarihHatasi("tarih ifadesi boş")
    s = _kucuk(ifade)

    # Göreli gün ifadeleri ayrı kurallarla çözülür ve aynı kurallar çözüm izini de sağlar.
    if not _AYNI_GUN_RE.search(s) and re.search(r"today|tomorrow|yesterday|day|days|week|hafta|bugun|yarin|dun|onceki|obur|pazartesi|sali|carsamba|persembe|cuma|cumartesi|pazar|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|haftaya|ayin son|gelecek ay", _anahtar(s)):
        try:
            return tarih_coz_detay(ifade, referans).tarih
        except TarihHatasi:
            # Tarih + haftanın günü gibi mevcut birleşik biçimler aşağıda denetlenir.
            if not (re.search(r"\d", s) and _GUN_ADI.search(s)):
                raise

    # "Gelecek hafta" takvim haftasıdır (Pazartesi–Pazar), bugünden 7 gün sonrası değil.
    # Hafta kaydırıcısı varsa gün adı/o gün/belirli gün ifadesi bu haftaya taşınır.
    hafta = _HAFTAYA.search(s)
    if hafta:
        pazartesi = referans - timedelta(days=referans.weekday()) + timedelta(days=7)
        if s.strip() == "haftaya":
            raise TarihHatasi(f"'{ifade}' hangi gün olduğu belirtilmemiş")
        kalan = s[:hafta.start()] + " " + s[hafta.end():]
        kalan = kalan.strip(" ,")
        if not kalan or re.fullmatch(r"(?:bu\s+)?hafta", kalan):
            return pazartesi
        if m := _GUN_ADI.search(kalan):
            return pazartesi + timedelta(days=_GUNLER[m[1]])
        if _GORELI_RE.search(kalan):
            rel = _GORELI_RE.search(kalan)
            return pazartesi + timedelta(days=_GORELI[rel[1]])
        # "gelecek hafta 12 Ekim" gibi açık tarihlerde, tarihin haftasını koru.
        if d := tarihleri_bul(kalan, referans):
            return d[0]
        raise TarihHatasi(f"'{ifade}' gelecek haftanın gününe çözülemedi")

    if _AYNI_GUN_RE.search(s) and not re.search(r"\d", s):
        adaylar = tarihleri_bul(baglam or "", referans)
        if len(adaylar) == 1:
            return adaylar[0]
        raise TarihHatasi(f"'{ifade}' bir atıf; mesajda tek bir açık tarih yok "
                          f"({len(adaylar)} tarih bulundu)")

    tarih: date | None = None
    if m := _ISO.search(s):
        tarih = _yil_tamamla(int(m[3]), int(m[2]), int(m[1]), referans)
    elif m := _GUN_AY.search(s):
        tarih = _yil_tamamla(int(m[1]), _AYLAR[m[2]], int(m[3]) if m[3] else None, referans)
    elif m := _AY_GUN.search(s):
        tarih = _yil_tamamla(int(m[2]), _AYLAR[m[1]], int(m[3]) if m[3] else None, referans)
    elif m := _SAYISAL.search(s):
        tarih = _yil_tamamla(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, referans)

    gun_adi = _GUN_ADI.search(s)
    if tarih is not None:
        if gun_adi and _GUNLER[gun_adi[1]] != tarih.weekday():
            raise TarihHatasi(
                f"'{ifade}': tarih {tarih.isoformat()} ile gün adı '{gun_adi[1]}' tutarsız"
            )
        return tarih
    if gun_adi:
        return _sonraki_gun_adi(_GUNLER[gun_adi[1]], referans)
    if m := _GORELI_RE.search(s):
        return referans + timedelta(days=_GORELI[m[1]])
    raise TarihHatasi(f"'{ifade}' kesin bir tarihe çözülemedi")
