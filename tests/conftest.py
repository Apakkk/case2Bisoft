import json
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from detention.schema import CikarimSonucu, MesajCikarimi  # noqa: E402
from detention.veri import mesajlari_yukle  # noqa: E402


@pytest.fixture
def mesajlar():
    return mesajlari_yukle(KOK / "data" / "messages.json")


@pytest.fixture
def beklenen_cikarim():
    return json.loads((KOK / "tests" / "fixtures" / "beklenen_cikarim.json").read_text(encoding="utf-8"))


@pytest.fixture
def altin_sonuclar(mesajlar, beklenen_cikarim):
    """Modelin 'doğru' çıktısını verdiği varsayımıyla çıkarım sonuçları (LLM'siz uçtan uca test)."""
    return [CikarimSonucu(mesaj=m, cikarim=MesajCikarimi.model_validate(beklenen_cikarim[m.id]))
            for m in mesajlar]
