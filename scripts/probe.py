"""Genelleme yoklaması: case'te olmayan varyasyon mesajlarını canlı modelden geçirir.

Kullanım (sunucu açıkken):  uv run python scripts/probe.py
Her mesaj için mesaj tipi, kritik alanlar, deneme sayısı ve (varsa) reddedilme sebebi yazdırılır.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from detention.dates import TarihHatasi, tarih_coz  # noqa: E402
from detention.extract import cikar  # noqa: E402
from detention.llm import istemci  # noqa: E402
from detention.schema import Mesaj  # noqa: E402


def main() -> None:
    client = istemci()
    for satir in json.loads((KOK / "data" / "probe_messages.json").read_text(encoding="utf-8")):
        beklenen = satir.pop("beklenen")
        m = Mesaj.model_validate(satir)
        s, _ = cikar(client, m)
        print(f"\n{m.id}: {m.metin}\n   beklenen: {beklenen}")
        if s.cikarim is None:
            print(f"   SONUÇ: MANUEL İNCELEME ({s.deneme} deneme) -> {'; '.join(s.hatalar)}")
            continue
        c = s.cikarim
        iade = "-"
        if c.iade_ifadesi and c.iade_kesinligi in ("kesin_tarih", "goreli_gun"):
            try:
                iade = tarih_coz(c.iade_ifadesi, m.tarih, baglam=m.metin).isoformat()
            except TarihHatasi as e:
                iade = f"çözülemedi ({e})"
        print(f"   model: {c.mesaj_tipi} | no={c.konteyner_no_ham} | gate_out={c.gate_out_ifadesi} | "
              f"serbest={c.serbest_sure_gun} {c.serbest_sure_tipi} | "
              f"ücret={[(k.gun_sayisi, k.usd_gunluk) for k in c.ucret_kademeleri]} | "
              f"iade={c.iade_ifadesi!r} ({c.iade_kesinligi}) -> {iade} | deneme={s.deneme} {s.sure_sn}s")
        if s.hatalar:
            print(f"   reddedilen denemeler: {'; '.join(s.hatalar)}")


if __name__ == "__main__":
    main()
