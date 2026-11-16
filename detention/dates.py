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
"""
from __future__ import annotations

import re
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
