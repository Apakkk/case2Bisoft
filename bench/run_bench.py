"""Bir modeli (açık llama-server üzerinden) bench/dataset.json ile ölçer.

Kullanım: uv run python bench/run_bench.py --model-adi <ad> --model-yolu <gguf> [--port 8080]
Çıktı: bench/results/<ad>.json (mesaj bazında ham sonuçlar + özet metrikler)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "tests"))

from detention import config  # noqa: E402
from detention.container import normalize_konteyner  # noqa: E402
from detention.dates import TarihHatasi, tarih_coz  # noqa: E402
from detention.schema import CikarimSonucu, Mesaj, MesajCikarimi  # noqa: E402

ALANLAR = ["mesaj_tipi", "konteyner_no_ham", "gate_out_ifadesi", "serbest_sure_gun", "serbest_sure_tipi",
           "ucret_kademeleri", "iade_ifadesi", "iade_kesinligi"]


def _tarih(ifade, m: Mesaj):
    if not ifade:
        return None
    try:
        return tarih_coz(ifade, m.tarih, baglam=m.metin).isoformat()
    except TarihHatasi:
        return "ÇÖZÜLEMEDİ:" + ifade.strip().lower()


def _iade_tarihi(c: dict | None, m: Mesaj):
    if c is None:
        return "YOK"
    if c["iade_kesinligi"] in ("kesin_tarih", "goreli_gun"):
        return _tarih(c["iade_ifadesi"], m)
    return c["iade_kesinligi"]  # belirsiz / yok


def alan_esit(alan: str, cv, bv, m: Mesaj) -> bool:
    if alan == "konteyner_no_ham":
        return normalize_konteyner(cv) == normalize_konteyner(bv)
    if alan == "ucret_kademeleri":
        return [(k["gun_sayisi"], float(k["usd_gunluk"])) for k in cv] == \
               [(k["gun_sayisi"], float(k["usd_gunluk"])) for k in bv]
    if alan in ("gate_out_ifadesi", "iade_ifadesi"):
        return _tarih(cv, m) == _tarih(bv, m)  # "12 Ekim" == "12 Ekim'e"
    return cv == bv


def rss_mb() -> float | None:
    try:
        pid = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True).stdout.split()[0]
        return int(subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True).stdout) / 1024
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model-adi", required=True)
    p.add_argument("--model-yolu", required=True)
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args()
    config.LLM_BASE_URL = f"http://127.0.0.1:{a.port}/v1"
    config.MODEL_ADI = a.model_adi

    from detention.extract import cikar
    from detention.llm import cagir, istemci
    from detention.prompt import mesaj_listesi

    veri = json.loads((KOK / "bench" / "dataset.json").read_text(encoding="utf-8"))
    client = istemci()
    isinma = None
    try:  # ısınma: prompt öneki önbelleğe girsin, ilk mesajın süresi bozulmasın
        cagir(client, mesaj_listesi(Mesaj(id="W", tarih="2026-10-01", gonderen="Hat şirketi",
                                          metin="Container TCLU1234561 gated out 1 Oct.")))
    except Exception as e:  # noqa: BLE001
        isinma = f"{type(e).__name__}: {e}"[:400]

    kayitlar, ust_uste_baglanti = [], 0
    for v in veri:
        m = Mesaj.model_validate({k: v[k] for k in ("id", "tarih", "gonderen", "metin")})
        t0 = time.perf_counter()
        try:
            s, denemeler = cikar(client, m)
            hata, ust_uste_baglanti = None, 0
        except Exception as e:  # noqa: BLE001  (bağlantı, HTTP 500, düşünme açık...)
            s, denemeler, hata = None, [], f"{type(e).__name__}: {e}"[:400]
            ust_uste_baglanti = ust_uste_baglanti + 1 if "Connection" in type(e).__name__ else 0
        k = {"id": v["id"], "kategori": v["kategori"], "koruma_reddeder": v["koruma_reddeder"],
             "sure_sn": round(time.perf_counter() - t0, 2), "istisna": hata,
             "deneme": s.deneme if s else 0, "hatalar": s.hatalar if s else [hata],
             "cikarim": s.cikarim.model_dump() if s and s.cikarim else None,
             "denemeler": [{"icerik": d.get("icerik"), "hata": d.get("hata"),
                            "completion_tokens": d.get("completion_tokens"),
                            "gen_tok_s": (d.get("timings") or {}).get("predicted_per_second")} for d in denemeler]}
        kayitlar.append(k)
        print(f"  {a.model_adi} {v['id']:<4} {'ok' if k['cikarim'] else 'YOK':<4} {k['sure_sn']:>6.2f}s "
              f"deneme={k['deneme']} {(hata or '; '.join(k['hatalar']))[:150]}", flush=True)
        if ust_uste_baglanti >= 3:
            print("  sunucuya 3 kez üst üste bağlanılamadı, model atlanıyor", flush=True)
            break

    # --- metrikler ---------------------------------------------------------------------------
    mesaj = {v["id"]: Mesaj.model_validate({k: v[k] for k in ("id", "tarih", "gonderen", "metin")}) for v in veri}
    beklenen = {v["id"]: v["beklenen"] for v in veri}
    alan_top = alan_dog = tip = iade = 0
    belirsiz_n = belirsiz_ok = sema_n = sema_ok = 0
    yanlislar = []
    for k in kayitlar:
        b, c, m = beklenen[k["id"]], k["cikarim"], mesaj[k["id"]]
        for d in k["denemeler"]:
            sema_n += 1
            try:
                MesajCikarimi.model_validate_json(d["icerik"] or "")
                sema_ok += 1
            except Exception:  # noqa: BLE001
                pass
        tip += bool(c and c["mesaj_tipi"] == b["mesaj_tipi"])
        iade += _iade_tarihi(c, m) == _iade_tarihi(b, m)
        if b["iade_kesinligi"] == "belirsiz":
            belirsiz_n += 1
            belirsiz_ok += bool(c and c["iade_kesinligi"] == "belirsiz")
        for alan in ALANLAR:
            alan_top += 1
            if c is not None and alan_esit(alan, c[alan], b[alan], m):
                alan_dog += 1
            else:
                yanlislar.append(f"{k['id']}.{alan}: model={None if c is None else c[alan]!r} beklenen={b[alan]!r}")

    # case uçtan uca (M1-M13): 6 konteynerin kaçı beklenen tabloyla aynı?
    from test_deterministik import BEKLENEN_TABLO  # noqa: E402
    from detention.merge import hesapla
    case = [CikarimSonucu(mesaj=mesaj[k["id"]], cikarim=MesajCikarimi.model_validate(k["cikarim"]) if k["cikarim"] else None,
                          hatalar=k["hatalar"] or []) for k in kayitlar if k["kategori"] == "case"]
    case_dogru = None
    if len(case) == 13:
        satirlar, _ = hesapla(case, konteyner_formati="basit", as_of=date(2026, 10, 5))
        sonuc = {s.konteyner_no: (s.son_serbest_gun, s.kalan_gun, s.planlanan_iade, s.tahmini_ucret_usd, s.risk)
                 for s in satirlar}
        case_dogru = sum(sonuc.get(no) == v for no, v in BEKLENEN_TABLO.items())

    sureler = [k["sure_sn"] for k in kayitlar]
    hizlar = [d["gen_tok_s"] for k in kayitlar for d in k["denemeler"] if d["gen_tok_s"]]
    tokenler = [d["completion_tokens"] for k in kayitlar for d in k["denemeler"] if d["completion_tokens"]]
    n = len(kayitlar)
    ozet = {
        "model": a.model_adi, "dosya": Path(a.model_yolu).name,
        "boyut_gb": round(os.path.getsize(a.model_yolu) / 1e9, 2), "n": n, "isinma_hatasi": isinma,
        "sema_gecerli": f"{sema_ok}/{sema_n}",
        "tip_dogrulugu": round(tip / n, 3) if n else 0,
        "alan_dogrulugu": round(alan_dog / alan_top, 3) if alan_top else 0,
        "iade_tarihi_dogrulugu": round(iade / n, 3) if n else 0,
        "belirsiz_yakalama": f"{belirsiz_ok}/{belirsiz_n}",
        "ilk_denemede_gecen": sum(1 for k in kayitlar if k["cikarim"] and k["deneme"] == 1),
        "manuel": sum(1 for k in kayitlar if not k["cikarim"]),
        "case_konteyner_dogru": case_dogru,
        "medyan_sn": round(statistics.median(sureler), 2) if sureler else None,
        "p90_sn": round(statistics.quantiles(sureler, n=10)[-1], 2) if len(sureler) >= 10 else None,
        "toplam_sn": round(sum(sureler), 1),
        "medyan_uretim_tok_s": round(statistics.median(hizlar), 1) if hizlar else None,
        "medyan_cikti_token": statistics.median(tokenler) if tokenler else None,
        "rss_mb": round(rss_mb() or 0),
    }
    cikti = KOK / "bench" / "results" / f"{a.model_adi}.json"
    cikti.write_text(json.dumps({"ozet": ozet, "yanlis_alanlar": yanlislar, "kayitlar": kayitlar},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ozet, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
