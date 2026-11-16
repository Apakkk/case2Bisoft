"""Detention riski CLI.

Örnekler:
  uv run python run.py --konteyner-formati basit              # canlı model (llama-server açık olmalı)
  uv run python run.py --konteyner-formati basit --offline    # cache'teki model çıktılarıyla
  uv run python run.py --konteyner-formati iso6346 --offline  # ISO 6346 doğrulamasıyla
  uv run python run.py --konteyner-formati basit --altin      # modelsiz: beklenen çıkarımlarla
  uv run python run.py --konteyner-formati basit --as-of 2026-10-07
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

from detention import config
from detention.container import KONTEYNER_FORMATLARI
from detention.merge import hesapla
from detention.report import (atlanan_metni, bugun_notu, dogruluk_ozeti, dosyalara_yaz, gerekceler,
                              tablo, uyarilar)
from detention.schema import CikarimSonucu, MesajCikarimi
from detention.veri import mesajlari_yukle, varsayilan_as_of

BEKLENEN = config.KOK / "tests" / "fixtures" / "beklenen_cikarim.json"


def konteyner_formati_sor(verilen: str | None) -> str:
    """Format sessizce varsayılmaz: verilmediyse bir kez sorulur."""
    if verilen:
        return verilen
    if not sys.stdin.isatty():
        sys.exit("--konteyner-formati verilmeli (basit | iso6346)")
    print("Konteyner numarası formatı?\n"
          "  1) basit   : 4 harf + 7 rakam\n"
          "  2) iso6346 : ayrıca 4. harf U/J/Z ve kontrol hanesi tutmalı")
    while True:
        c = input("Seçim [1/2]: ").strip().lower()
        if c in ("1", "basit"):
            return "basit"
        if c in ("2", "iso6346"):
            return "iso6346"


def _cache_klasoru() -> Path:
    return config.CACHE_DIR / config.MODEL_ADI


def canli_cikarim(mesajlar) -> list[CikarimSonucu]:
    from detention.extract import cikar
    from detention.llm import istemci

    client = istemci()
    klasor = _cache_klasoru()
    klasor.mkdir(parents=True, exist_ok=True)
    sonuclar = []
    for m in mesajlar:
        s, denemeler = cikar(client, m)
        durum = "ok" if s.cikarim else "MANUEL"
        print(f"  {m.id:<4} {durum:<6} {s.sure_sn:>5.2f} sn  deneme={s.deneme}"
              + (f"  ({'; '.join(s.hatalar)})" if s.hatalar else ""), flush=True)
        (klasor / f"{m.id}.json").write_text(json.dumps({
            "mesaj": m.model_dump(mode="json"), "denemeler": denemeler,
            "sonuc": s.model_dump(mode="json")}, ensure_ascii=False, indent=2), encoding="utf-8")
        sonuclar.append(s)
    return sonuclar


def offline_cikarim(mesajlar) -> list[CikarimSonucu]:
    klasor = _cache_klasoru()
    sonuclar = []
    for m in mesajlar:
        yol = klasor / f"{m.id}.json"
        if not yol.exists():
            sys.exit(f"cache yok: {yol}. Önce canlı modelle bir kez çalıştırın.")
        kayit = json.loads(yol.read_text(encoding="utf-8"))
        s = CikarimSonucu.model_validate(kayit["sonuc"])
        if s.mesaj.metin != m.metin:
            sys.exit(f"{m.id} cache'teki mesajla aynı değil; canlı modelle yeniden çalıştırın.")
        sonuclar.append(s)
    return sonuclar


def altin_cikarim(mesajlar) -> list[CikarimSonucu]:
    b = json.loads(BEKLENEN.read_text(encoding="utf-8"))
    return [CikarimSonucu(mesaj=m, cikarim=MesajCikarimi.model_validate(b[m.id])) for m in mesajlar]


def _canli_ya_da_cik(mesajlar) -> list[CikarimSonucu]:
    """Sunucu sorunlarında ham hata dökümü yerine ne yapılacağını söyleyen tek satırla çıkar."""
    import openai

    from detention.llm import DusunmeAcikHatasi

    try:
        return canli_cikarim(mesajlar)
    except openai.APIConnectionError:
        sys.exit(f"\nHATA: llama-server'a bağlanılamadı ({config.LLM_BASE_URL}).\n"
                 "  Sunucuyu başlatın:  ./scripts/start_server.sh\n"
                 "  ya da kayıtlı model çıktılarıyla çalıştırın:  --offline")
    except openai.APIStatusError as e:
        sys.exit(f"\nHATA: llama-server isteği reddetti (HTTP {e.status_code}): {str(e)[:300]}\n"
                 "  Kayıtlı model çıktılarıyla çalıştırmak için:  --offline")
    except DusunmeAcikHatasi as e:
        sys.exit(f"\nHATA: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Konteyner bazında detention riski")
    p.add_argument("--konteyner-formati", choices=KONTEYNER_FORMATLARI,
                   help="verilmezse başlarken sorulur")
    p.add_argument("--as-of", type=date.fromisoformat,
                   help="hesap tarihi (YYYY-MM-DD); varsayılan: en son mesajın tarihi")
    p.add_argument("--mesajlar", type=Path, default=config.MESAJLAR)
    kaynak = p.add_mutually_exclusive_group()
    kaynak.add_argument("--offline", action="store_true", help="cache'teki model çıktılarını kullan")
    kaynak.add_argument("--altin", action="store_true",
                        help="modelsiz demo: beklenen çıkarımlarla yalnızca deterministik katman")
    args = p.parse_args()

    format_ = konteyner_formati_sor(args.konteyner_formati)
    mesajlar = mesajlari_yukle(args.mesajlar)
    # Canlı operasyonda bugünün tarihi gerekir; offline/altın senaryoları ise
    # mesaj kümesinin tarihiyle tekrarlanabilir kalır.
    as_of = args.as_of or (date.today() if not (args.offline or args.altin)
                           else varsayilan_as_of(mesajlar))

    if args.altin:
        mod, sonuclar = "altın (modelsiz)", altin_cikarim(mesajlar)
    elif args.offline:
        mod, sonuclar = f"offline cache ({config.MODEL_ADI})", offline_cikarim(mesajlar)
    else:
        mod = f"canlı ({config.MODEL_ADI} @ {config.LLM_BASE_URL})"
        print(f"Model çıkarımı: {len(mesajlar)} mesaj")
        sonuclar = _canli_ya_da_cik(mesajlar)

    satirlar, atlananlar = hesapla(sonuclar, konteyner_formati=format_, as_of=as_of)

    print(f"\nKaynak: {mod} | Konteyner formatı: {format_}")
    print(bugun_notu(as_of))
    print("\n" + tablo(satirlar))
    print("\nGerekçeler:\n" + gerekceler(satirlar))
    print("\nOperasyon ekibine uyarılar:\n" + uyarilar(satirlar))
    print("\nAtlanan mesajlar:\n" + atlanan_metni(atlananlar))

    sureler = [s.sure_sn for s in sonuclar if s.sure_sn]
    if sureler and not args.altin:
        print(f"\nGecikme: mesaj başına medyan {statistics.median(sureler):.2f} sn, "
              f"toplam {sum(sureler):.1f} sn")
    if not args.altin and args.mesajlar == config.MESAJLAR:
        print("\n" + dogruluk_ozeti(sonuclar, json.loads(BEKLENEN.read_text(encoding="utf-8"))))

    j, c = dosyalara_yaz(satirlar, atlananlar,
                         {"kaynak": mod, "konteyner_formati": format_, "as_of": as_of.isoformat()},
                         config.OUT_DIR)
    print(f"\nYazıldı: {j.relative_to(config.KOK)}, {c.relative_to(config.KOK)}")


if __name__ == "__main__":
    main()
