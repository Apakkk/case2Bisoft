"""Ayarlar. Hepsi ortam değişkeniyle değiştirilebilir; model dosyası projeye kopyalanmaz."""
from __future__ import annotations

import os
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent

MODEL_PATH = Path(os.environ.get(
    "DETENTION_MODEL_PATH",
    str(Path.home() / "case2/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf"),
))
MODEL_ADI = os.environ.get("DETENTION_MODEL_ADI", "qwen3.5-4b-q4_k_m")  # cache klasör adı
LLM_BASE_URL = os.environ.get("DETENTION_LLM_URL", "http://127.0.0.1:8080/v1")

# Sampling: deterministik çıkarım.
TEMPERATURE = 0.0
SEED = 42
MAX_TOKENS = 400        # döngüye giren üretimi keser; normal çıktı ~120-180 token
DENEME_SAYISI = 2       # 1 ilk deneme + 1 hata geri bildirimli yeniden deneme
ISTEK_ZAMAN_ASIMI_SN = 120

CACHE_DIR = KOK / "cache"
OUT_DIR = KOK / "out"
MESAJLAR = KOK / "data" / "messages.json"
