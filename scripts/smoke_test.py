"""llama-server duman testi: sunucu ayakta mı, thinking kapalı mı, json_schema çalışıyor mu, hız.

Kullanım (sunucu açıkken):  uv run python scripts/smoke_test.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detention import config  # noqa: E402
from detention.llm import cagir, istemci  # noqa: E402
from detention.prompt import mesaj_listesi  # noqa: E402
from detention.schema import Mesaj, MesajCikarimi  # noqa: E402

KOK_URL = config.LLM_BASE_URL.removesuffix("/v1")


def get(yol: str) -> dict:
    with urllib.request.urlopen(KOK_URL + yol, timeout=10) as r:
        return json.loads(r.read())


def main() -> int:
    ok = True
    print("1) /health:", get("/health"))
    props = get("/props")
    print("   build:", props.get("build_info"), "| model:", Path(props.get("model_path", "?")).name)

    m = Mesaj(id="T", tarih="2026-10-05", gonderen="Sürücü",
              metin="MSCU 482915-3 perşembe iade ediyoruz.")
    client = istemci()
    cagir(client, mesaj_listesi(m))  # ısınma + prompt önek önbelleği
    t0 = time.perf_counter()
    cevap = cagir(client, mesaj_listesi(m))
    sure = time.perf_counter() - t0

    print("2) thinking kapalı:", "EVET" if not cevap.reasoning else "HAYIR")
    print("   content '{' ile başlıyor:", cevap.icerik.lstrip().startswith("{"))
    try:
        c = MesajCikarimi.model_validate_json(cevap.icerik)
        print("3) json_schema + Pydantic: GEÇERLİ ->", c.model_dump(exclude={"kanit"}))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("3) json_schema + Pydantic: GEÇERSİZ ->", e, "\n", cevap.icerik)

    tps = (cevap.completion_tokens or 0) / sure if sure else 0
    print(f"4) süre {sure:.2f} sn | prompt {cevap.prompt_tokens} tok | "
          f"çıktı {cevap.completion_tokens} tok | ~{tps:.1f} tok/sn (uçtan uca) | "
          f"finish={cevap.finish_reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
