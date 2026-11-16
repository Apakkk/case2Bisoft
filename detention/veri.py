"""Girdi mesajlarını yükleme ve hesap tarihi (as_of) varsayılanı."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .schema import Mesaj


def mesajlari_yukle(yol: str | Path) -> list[Mesaj]:
    return [Mesaj.model_validate(m) for m in json.loads(Path(yol).read_text(encoding="utf-8"))]


def varsayilan_as_of(mesajlar: list[Mesaj]) -> date:
    """Hesap tarihi = en son mesajın tarihi (case için 05.10.2026).

    `date.today()` KULLANILMAZ: bugün (Kasım 2026) alınsaydı bütün son serbest günler geçmiş
    görünür, MAEU "Orta" yerine "Yüksek" çıkar ve kalan gün sütunu tamamen yanlış olurdu.
    Canlı sistemde --as-of ile bugünün tarihi verilir.
    """
    return max(m.tarih for m in mesajlar)
