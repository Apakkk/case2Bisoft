"""Case kurallarının birebir kod karşılığı: serbest süre, detention günleri, ücret, risk.

KURALLAR (case metninden)
- Serbest süre, gate-out gününün ertesi günü başlar.
- Serbest süre "iş günü" ise hafta sonları sayılmaz; aksi halde takvim günüdür.
  (Tip belirtilmemişse -> takvim günü.)
- Detention günleri takvim günüdür: son serbest günden sonraki günden iade günü dahil sayılır.
- Yüksek: ücret > 0 ve (son serbest gün geçmiş veya ücret >= $500)
- Orta:   ücret > 0, diğer durumlar
- Düşük:  ücret 0
- Belirsiz: iade tarihi bilinmiyor (manuel inceleme)
Resmi tatiller sayılmaz: limanın ülkesi bilinmiyor (genişletme: `holidays` paketi).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

YUKSEK_ESIK_USD = 500


@dataclass(frozen=True)
class Kademe:
    gun_sayisi: int | None  # None = "bundan sonrası" (thereafter) ya da tek sabit ücret
    usd_gunluk: float


def son_serbest_gun(gate_out: date, serbest_gun: int, is_gunu: bool) -> date:
    if serbest_gun < 0:
        raise ValueError("serbest gün negatif olamaz")
    if not is_gunu:
        return gate_out + timedelta(days=serbest_gun)
    gun, sayilan = gate_out, 0
    while sayilan < serbest_gun:
        gun += timedelta(days=1)
        if gun.weekday() < 5:  # Pzt-Cum
            sayilan += 1
    return gun


def detention_gun_sayisi(son_serbest: date, iade: date) -> int:
    """Son serbest günden sonraki günden iade günü dahil, takvim günü."""
    return max(0, (iade - son_serbest).days)


def kademeli_ucret(gun: int, kademeler: list[Kademe]) -> tuple[float, list[str]]:
    """Toplam ücret ve okunabilir döküm. Kademeler sırayla uygulanır.

    Bütün kademeler sonluysa ve gün sayısı onları aşarsa, kalan günlere son kademenin
    ücreti uygulanır ve dökümde bu açıkça belirtilir.
    """
    if gun <= 0:
        return 0.0, []
    if not kademeler:
        raise ValueError("detention ücreti bilinmiyor")
    kalan, toplam, dokum = gun, 0.0, []
    for i, k in enumerate(kademeler):
        if kalan <= 0:
            break
        son_kademe = i == len(kademeler) - 1
        n = kalan if (k.gun_sayisi is None or son_kademe) else min(kalan, k.gun_sayisi)
        if son_kademe and k.gun_sayisi is not None and n > k.gun_sayisi:
            dokum.append(f"(kademeler {gun} günü kapsamıyor; kalan günlere son ücret uygulandı)")
        toplam += n * k.usd_gunluk
        dokum.append(f"{n} × ${k.usd_gunluk:g}")
        kalan -= n
    return toplam, dokum


def risk_seviyesi(ucret: float | None, son_serbest: date, as_of: date) -> str:
    """`ucret` None ise iade tarihi bilinmiyordur -> Belirsiz."""
    if ucret is None:
        return "Belirsiz"
    if ucret > 0 and (son_serbest < as_of or ucret >= YUKSEK_ESIK_USD):
        return "Yüksek"
    if ucret > 0:
        return "Orta"
    return "Düşük"
