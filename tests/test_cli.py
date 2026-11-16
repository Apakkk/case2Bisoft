"""CLI: sunucu kapalıyken ham hata dökümü yerine ne yapılacağını söyleyen mesaj."""
import openai
import pytest

import run


def test_sunucu_kapaliyken_anlasilir_mesaj(monkeypatch, mesajlar):
    def patla(_):
        # Gerçek bir HTTP isteği nesnesi kurmadan aynı hata tipini üret.
        raise openai.APIConnectionError.__new__(openai.APIConnectionError)

    monkeypatch.setattr(run, "canli_cikarim", patla)
    with pytest.raises(SystemExit) as e:
        run._canli_ya_da_cik(mesajlar)
    assert "start_server.sh" in str(e.value) and "--offline" in str(e.value)
