"""Gerçek modelle uçtan uca test. llama-server açıkken:  uv run pytest -m live -q"""
from datetime import date

import pytest

from detention.merge import hesapla

from test_deterministik import BEKLENEN_TABLO

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def canli_sonuclar():
    from detention.extract import cikar
    from detention.llm import istemci
    from detention.veri import mesajlari_yukle
    from detention import config

    client = istemci()
    return [cikar(client, m)[0] for m in mesajlari_yukle(config.MESAJLAR)]


def test_tum_mesajlar_dogrulamadan_gecer(canli_sonuclar):
    basarisiz = {s.mesaj.id: s.hatalar for s in canli_sonuclar if s.cikarim is None}
    assert not basarisiz


def test_mesaj_tipleri(canli_sonuclar, beklenen_cikarim):
    tipler = {s.mesaj.id: s.cikarim.mesaj_tipi for s in canli_sonuclar if s.cikarim}
    assert tipler == {k: v["mesaj_tipi"] for k, v in beklenen_cikarim.items()}


def test_uctan_uca_beklenen_tablo(canli_sonuclar):
    satirlar, _ = hesapla(canli_sonuclar, konteyner_formati="basit", as_of=date(2026, 10, 5))
    sonuc = {s.konteyner_no: (s.son_serbest_gun, s.kalan_gun, s.planlanan_iade,
                              s.tahmini_ucret_usd, s.risk) for s in satirlar}
    assert sonuc == BEKLENEN_TABLO
