"""bench/results/*.json özetlerini tek tabloda toplar -> bench/results/ozet.md"""
from __future__ import annotations

import json
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
SUTUNLAR = [("model", "Model"), ("boyut_gb", "GB"), ("tip_dogrulugu", "Tip"), ("alan_dogrulugu", "Alan"),
            ("iade_tarihi_dogrulugu", "İade tarihi"), ("belirsiz_yakalama", "Belirsiz"),
            ("ilk_denemede_gecen", "1. denemede"), ("manuel", "Manuel"), ("case_konteyner_dogru", "Case /6"),
            ("sema_gecerli", "Şema"), ("medyan_sn", "Medyan sn"), ("p90_sn", "p90 sn"),
            ("medyan_uretim_tok_s", "tok/s"), ("rss_mb", "RSS MB")]


def main() -> None:
    satirlar = []
    for f in sorted((KOK / "bench" / "results").glob("*.json")):
        o = json.loads(f.read_text(encoding="utf-8"))["ozet"]
        satirlar.append("| " + " | ".join(str(o.get(k, "-")) for k, _ in SUTUNLAR) + " |")
        if o.get("isinma_hatasi"):
            satirlar.append(f"| ↳ ısınma hatası: {o['isinma_hatasi'][:200]} |")
    md = ("| " + " | ".join(b for _, b in SUTUNLAR) + " |\n|" + "---|" * len(SUTUNLAR) + "\n"
          + "\n".join(satirlar) + "\n\nn=40 mesaj (13 case + 7 yoklama + 20 varyasyon). Tip/Alan/İade tarihi: oran; "
          "1. denemede ve Manuel: mesaj sayısı; Case /6: case tablosunda beklenenle aynı çıkan konteyner sayısı.\n")
    (KOK / "bench" / "results" / "ozet.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
