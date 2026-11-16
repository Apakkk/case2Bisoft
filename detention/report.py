"""Çıktı: konsol tablosu, uyarı metinleri, JSON/CSV ve model doğruluk özeti."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from .dates import TarihHatasi, tarih_coz
from .merge import Atlanan, tarih_yaz
from .schema import CikarimSonucu, SonucSatiri

ALANLAR = ["konteyner_no", "son_serbest_gun", "kalan_gun", "planlanan_iade",
           "tahmini_ucret_usd", "risk", "gerekce"]
_RISK_SIRA = {"Yüksek": 0, "Belirsiz": 1, "Manuel inceleme": 2, "Orta": 3, "Düşük": 4, "Kapsam dışı": 5}


def _ucret(v: float | None) -> str:
    return "-" if v is None else f"${v:,.0f}"


def tablo(satirlar: list[SonucSatiri]) -> str:
    basliklar = ["konteyner_no", "son_serbest_gun", "kalan_gun", "planlanan_iade",
                 "tahmini_ucret_usd", "risk"]
    veri = [[s.konteyner_no, tarih_yaz(s.son_serbest_gun),
             "-" if s.kalan_gun is None else str(s.kalan_gun),
             tarih_yaz(s.planlanan_iade) if s.planlanan_iade else
             ("bilinmiyor" if s.risk == "Belirsiz" else "-"),
             _ucret(s.tahmini_ucret_usd), s.risk] for s in satirlar]
    gen = [max(len(str(x)) for x in [b] + [r[i] for r in veri]) for i, b in enumerate(basliklar)]
    def satir(r): return "  ".join(str(x).ljust(gen[i]) for i, x in enumerate(r))
    return "\n".join([satir(basliklar), satir(["-" * g for g in gen])] + [satir(r) for r in veri])


def gerekceler(satirlar: list[SonucSatiri]) -> str:
    return "\n".join(f"- {s.konteyner_no} [{s.risk}]: {s.gerekce}" for s in satirlar)


def uyarilar(satirlar: list[SonucSatiri]) -> str:
    riskli = sorted((s for s in satirlar if s.uyari), key=lambda s: _RISK_SIRA[s.risk])
    if not riskli:
        return "Riskli konteyner yok."
    return "\n".join(f"[{s.risk}] {s.uyari}" for s in riskli)


def atlanan_metni(atlananlar: list[Atlanan]) -> str:
    return "\n".join(f"- {a.mesaj_id}: {a.sebep}" for a in atlananlar) or "-"


def dosyalara_yaz(satirlar: list[SonucSatiri], atlananlar: list[Atlanan], meta: dict,
                  klasor: Path) -> tuple[Path, Path]:
    klasor.mkdir(parents=True, exist_ok=True)
    j, c = klasor / "results.json", klasor / "results.csv"
    j.write_text(json.dumps({
        "meta": meta,
        "konteynerler": [s.model_dump(mode="json") for s in satirlar],
        "atlanan_mesajlar": [a.__dict__ for a in atlananlar],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with c.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ALANLAR + ["uyari"])
        for s in satirlar:
            d = s.model_dump(mode="json")
            w.writerow([d[a] if d[a] is not None else "" for a in ALANLAR] + [s.uyari or ""])
    return j, c


def dogruluk_ozeti(sonuclar: list[CikarimSonucu], beklenen: dict) -> str:
    """Model çıktısını beklenen çıkarımla alan alan karşılaştırır (normalizasyon sonrası)."""
    from .container import normalize_konteyner

    toplam = dogru = 0
    hatalar: list[str] = []
    for s in sonuclar:
        b = beklenen.get(s.mesaj.id)
        if b is None:
            continue
        if s.cikarim is None:
            hatalar.append(f"{s.mesaj.id}: çıkarım yok ({'; '.join(s.hatalar)})")
            toplam += len(b) - 1
            continue
        c = s.cikarim.model_dump()
        for alan, bv in b.items():
            if alan == "kanit":  # serbest alıntı; doğruluğu anlam kontrolü denetliyor
                continue
            cv = c[alan]
            if alan == "konteyner_no_ham":
                cv, bv = normalize_konteyner(cv), normalize_konteyner(bv)
            if alan == "ucret_kademeleri":
                cv = [(k["gun_sayisi"], float(k["usd_gunluk"])) for k in cv]
                bv = [(k["gun_sayisi"], float(k["usd_gunluk"])) for k in bv]
            if alan in ("gate_out_ifadesi", "iade_ifadesi") and cv and bv:
                # "12 Ekim" ile "12 Ekim'e" aynı tarih: çözülebiliyorsa tarih üzerinden karşılaştır.
                try:
                    cv, bv = (tarih_coz(cv, s.mesaj.tarih, baglam=s.mesaj.metin).isoformat(),
                              tarih_coz(bv, s.mesaj.tarih, baglam=s.mesaj.metin).isoformat())
                except TarihHatasi:
                    cv, bv = cv.strip().lower(), bv.strip().lower()
            toplam += 1
            if cv == bv:
                dogru += 1
            else:
                hatalar.append(f"{s.mesaj.id}.{alan}: model={cv!r} beklenen={bv!r}")
    oran = 100 * dogru / toplam if toplam else 0
    return f"Alan doğruluğu: {dogru}/{toplam} (%{oran:.1f})" + \
        ("".join(f"\n  - {h}" for h in hatalar) if hatalar else "")


def bugun_notu(as_of: date) -> str:
    return (f"Hesap tarihi (as_of): {tarih_yaz(as_of)}. Varsayılan = en son mesajın tarihi; "
            "canlı kullanımda --as-of ile bugünün tarihi verilir.")
