"""Lokal llama-server istemcisi (OpenAI uyumlu uç nokta, harici API yok).

Şema garantisi burada başlar: `response_format: json_schema` ile verilen şemadan
llama.cpp bir GBNF grammar türetir ve her adımda şemaya uymayan token'ları maskeler.
Çıktı bu yüzden her zaman şemaya uyan geçerli JSON'dur; doğruluğunu extract.py kontrol eder.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from openai import OpenAI

from . import config
from .schema import MesajCikarimi


class DusunmeAcikHatasi(RuntimeError):
    """Thinking kapalı değil: yapılandırma hatası, yeniden denemeyle düzelmez."""


@dataclass
class LlmCevap:
    icerik: str
    reasoning: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    sure_sn: float
    timings: dict | None = None  # llama-server: prompt_ms, predicted_ms, predicted_per_second...

    def dict(self) -> dict:
        return asdict(self)


def istemci() -> OpenAI:
    return OpenAI(base_url=config.LLM_BASE_URL, api_key="yerel",
                  timeout=config.ISTEK_ZAMAN_ASIMI_SN, max_retries=0)


def response_format() -> dict:
    return {"type": "json_schema",
            "json_schema": {"name": "mesaj_cikarimi", "strict": True,
                            "schema": MesajCikarimi.model_json_schema()}}


def cagir(client: OpenAI, mesajlar: list[dict]) -> LlmCevap:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=config.MODEL_ADI,  # llama-server tek model sunarken adı yok sayar
        messages=mesajlar,
        temperature=config.TEMPERATURE,
        seed=config.SEED,
        max_tokens=config.MAX_TOKENS,
        response_format=response_format(),
        # Sunucu --reasoning off ile açılıyor; istek düzeyinde de kapatmak ek güvence.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    sure = time.perf_counter() - t0
    secim = resp.choices[0]
    icerik = secim.message.content or ""
    reasoning = (secim.message.model_extra or {}).get("reasoning_content") or None
    if reasoning or "<think>" in icerik or not icerik.lstrip().startswith("{"):
        raise DusunmeAcikHatasi(
            "Model düşünce token'ı üretti ya da cevap '{' ile başlamıyor; sunucuyu "
            "--reasoning off ile başlatın (scripts/start_server.sh). "
            f"finish={secim.finish_reason} reasoning={len(reasoning or '')} karakter "
            f"icerik_basi={icerik[:120]!r}")
    u = resp.usage
    return LlmCevap(icerik, reasoning, secim.finish_reason,
                    u.prompt_tokens if u else None, u.completion_tokens if u else None, sure,
                    (resp.model_extra or {}).get("timings"))
