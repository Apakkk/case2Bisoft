"""Konteyner numarası: yakalama, normalizasyon ve format doğrulama.

Normalizasyon her zaman aynıdır: metinden 4 harf + 7 rakam yakalanır, boşluk ve
tire atılır ("MSCU 482915-3" -> "MSCU4829153"). Format doğrulama ise kullanıcının
seçtiği kurala göre ayrı bir adımda yapılır:

- "basit":   4 harf + 7 rakam yeterli.
- "iso6346": ayrıca 4. harf U/J/Z (kategori) olmalı ve kontrol hanesi tutmalı.

Numara hiçbir zaman otomatik düzeltilmez: kontrol hanesi tutmazsa hata seri
numarasında da olabilir, "düzeltilmiş" numara başka bir gerçek konteyneri gösterir.
"""
from __future__ import annotations

import re

# 4 harf, ardından 6 rakam seri + 1 kontrol hanesi; aralarda tek boşluk/tire olabilir.
# Sondaki \b, "HLCU 552018-7'nin" gibi Türkçe eklerde de doğru çalışır.
KONTEYNER_RE = re.compile(r"\b([A-Z]{4})[\s-]?(\d{3})[\s-]?(\d{3})[\s-]?(\d)\b")

KONTEYNER_FORMATLARI = ("basit", "iso6346")


def _harf_degerleri() -> dict[str, int]:
    """ISO 6346: A=10'dan başlar, 11'in katları (11, 22, 33) atlanır."""
    out, v = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        out[ch] = v
        v += 1
    return out


_HARF = _harf_degerleri()


def konteyner_bul(metin: str | None) -> list[str]:
    """Metindeki tüm konteyner numaralarını normalize edilmiş halde, sırayla ve tekil döner."""
    if not metin:
        return []
    goruldu: list[str] = []
    for m in KONTEYNER_RE.finditer(metin.upper()):
        no = "".join(m.groups())
        if no not in goruldu:
            goruldu.append(no)
    return goruldu


def normalize_konteyner(ham: str | None) -> str | None:
    bulunan = konteyner_bul(ham)
    return bulunan[0] if bulunan else None


def beklenen_kontrol_hanesi(no: str) -> int:
    toplam = sum((_HARF[c] if c.isalpha() else int(c)) * 2**i for i, c in enumerate(no[:10]))
    return toplam % 11 % 10


def konteyner_dogrula(no: str, konteyner_formati: str) -> tuple[bool, str]:
    """(geçerli mi, sebep). Format zorunlu parametredir; sessiz varsayılan yoktur."""
    if konteyner_formati not in KONTEYNER_FORMATLARI:
        raise ValueError(f"konteyner_formati {KONTEYNER_FORMATLARI} değerlerinden biri olmalı")
    if not re.fullmatch(r"[A-Z]{4}\d{7}", no or ""):
        return False, f"'{no}' 4 harf + 7 rakam biçiminde değil"
    if konteyner_formati == "basit":
        return True, "basit format: 4 harf + 7 rakam"
    if no[3] not in "UJZ":
        return False, f"ISO 6346: 4. harf U/J/Z olmalı, '{no[3]}' bulundu"
    beklenen = beklenen_kontrol_hanesi(no)
    if beklenen != int(no[10]):
        return False, f"ISO 6346: kontrol hanesi tutmuyor (yazılan {no[10]}, hesaplanan {beklenen})"
    return True, "ISO 6346: kontrol hanesi geçerli"
