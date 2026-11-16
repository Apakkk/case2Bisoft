"""Anlam kontrolü: doğru çıktıyı geçirmeli, uydurmayı yakalamalı. Şemanın llama.cpp uyumu."""
import pytest

from detention.extract import AnlamHatasi, anlam_kontrolu
from detention.llm import response_format
from detention.schema import MesajCikarimi


def test_altin_ciktilar_anlam_kontrolunden_gecer(mesajlar, beklenen_cikarim):
    for m in mesajlar:
        anlam_kontrolu(MesajCikarimi.model_validate(beklenen_cikarim[m.id]), m)


@pytest.mark.parametrize("mid, bozma, beklenen_hata", [
    ("M1", {"ucret_kademeleri": [{"gun_sayisi": None, "usd_gunluk": 175}]}, "ücret 175"),
    ("M1", {"serbest_sure_gun": 7}, "serbest süre 7"),
    ("M1", {"serbest_sure_tipi": "is_gunu"}, "iş günü"),
    ("M4", {"iade_ifadesi": "7 Ekim"}, "iade_ifadesi"),
    ("M9", {"konteyner_no_ham": "MSCU 482915-4"}, "eşleşmiyor"),
    ("M11", {"iade_ifadesi": "12 Ekim", "iade_kesinligi": "kesin_tarih"}, "iade_ifadesi"),
    ("M13", {"mesaj_tipi": "gate_out_bildirimi"}, "konteyner numarası yok"),
    ("M12", {"mesaj_tipi": "ilgisiz", "konteyner_no_ham": None}, "ilgisiz"),
    ("M2", {"kanit": "gated out on 02 Oct"}, "kanit"),
])
def test_uydurma_yakalanir(mesajlar, beklenen_cikarim, mid, bozma, beklenen_hata):
    m = next(x for x in mesajlar if x.id == mid)
    c = MesajCikarimi.model_validate({**beklenen_cikarim[mid], **bozma})
    with pytest.raises(AnlamHatasi, match=beklenen_hata):
        anlam_kontrolu(c, m)


# Canlı çalıştırmada (Qwen3.5-4B Q4_K_M, ilk prompt) modelin gerçekten ürettiği hatalı çıktılar.
@pytest.mark.parametrize("mid, bozma, beklenen_hata", [
    ("M4", {"mesaj_tipi": "gate_out_bildirimi", "gate_out_ifadesi": "6 Ekim'de"}, "gate-out ifadesi yok"),
    ("M10", {"mesaj_tipi": "gate_out_bildirimi", "gate_out_ifadesi": "9 Ekim"}, "gate-out ifadesi yok"),
    ("M11", {"iade_ifadesi": "haftaya", "iade_kesinligi": "goreli_gun"}, "cannot be resolved"),
])
def test_canli_calistirmada_gorulen_hatalar_yakalanir(mesajlar, beklenen_cikarim, mid, bozma, beklenen_hata):
    m = next(x for x in mesajlar if x.id == mid)
    c = MesajCikarimi.model_validate({**beklenen_cikarim[mid], **bozma})
    with pytest.raises(AnlamHatasi, match=beklenen_hata):
        anlam_kontrolu(c, m)


def test_ayni_gun_mesajdaki_tarihe_cozulur_ve_kabul_edilir(mesajlar, beklenen_cikarim, altin_sonuclar):
    """Canlı modelin M10 için yazdığı 'aynı gün' (birebir kopya) kabul edilir; kod 9 Ekim'e çözer."""
    from datetime import date

    from detention.merge import hesapla
    from detention.schema import CikarimSonucu

    m10 = next(x for x in mesajlar if x.id == "M10")
    c = MesajCikarimi.model_validate({**beklenen_cikarim["M10"], "iade_ifadesi": "aynı gün",
                                      "iade_kesinligi": "goreli_gun"})
    anlam_kontrolu(c, m10)
    sonuclar = [CikarimSonucu(mesaj=m10, cikarim=c) if s.mesaj.id == "M10" else s for s in altin_sonuclar]
    satirlar, _ = hesapla(sonuclar, konteyner_formati="basit", as_of=date(2026, 10, 5))
    maeu = next(s for s in satirlar if s.konteyner_no == "MAEU7731042")
    assert (maeu.planlanan_iade, maeu.tahmini_ucret_usd, maeu.risk) == (date(2026, 10, 9), 200.0, "Orta")
    assert "mesajdaki tarihe atıf" in maeu.gerekce


def test_sema_her_alani_zorunlu_kilar_ve_ek_alani_yasaklar():
    sema = response_format()["json_schema"]["schema"]
    assert set(sema["required"]) == set(MesajCikarimi.model_fields)
    assert sema["additionalProperties"] is False
    assert sema["$defs"]["UcretKademesi"]["additionalProperties"] is False


# --- Case kontrolünden sonra eklenen düzeltmeler ---------------------------------------------
def _mesaj(metin, tarih="2026-10-06"):
    from detention.schema import Mesaj
    return Mesaj(id="T", tarih=tarih, gonderen="Hat şirketi", metin=metin)


def _gate_out(no, gate, gun, tip, ucret, kanit):
    return MesajCikarimi.model_validate({
        "kanit": kanit, "mesaj_tipi": "gate_out_bildirimi", "konteyner_no_ham": no, "gate_out_ifadesi": gate,
        "serbest_sure_gun": gun, "serbest_sure_tipi": tip,
        "ucret_kademeleri": [{"gun_sayisi": None, "usd_gunluk": ucret}], "iade_ifadesi": None, "iade_kesinligi": "yok"})


@pytest.mark.parametrize("metin, gate", [
    ("Container SEGU2840193 left the port on 06 Oct 2026. Free time 4 days. USD 80/day.", "06 Oct 2026"),
    ("SEGU2840193 departed the terminal 06 Oct 2026. Free time 4 days. USD 80/day.", "06 Oct 2026"),
    ("SEGU2840193 06.10.2026 tarihinde limandan çıkış yaptı. Free time 4 gün, USD 80/gün.", "06.10.2026"),
])
def test_gate_out_ifade_listesi_genisletildi(metin, gate):
    anlam_kontrolu(_gate_out("SEGU2840193", gate, 4, "belirtilmemis", 80, gate), _mesaj(metin))


@pytest.mark.parametrize("metin, gun, tip", [
    ("OOCU 771045-2 gated out 21 Oct. Free time five calendar days. USD 140/day.", 5, "takvim"),
    ("OOCU7710452 gated out 21 Oct. Ten free days. USD 140/day.", 10, "belirtilmemis"),
    ("OOCU7710452 gated out 21 Oct. Serbest süre beş iş günü, USD 140/gün.", 5, "is_gunu"),
])
def test_yaziyla_gun_sayisi_kabul_edilir(metin, gun, tip):
    anlam_kontrolu(_gate_out("OOCU7710452", "21 Oct", gun, tip, 140, "gated out 21 Oct"), _mesaj(metin))


@pytest.mark.parametrize("metin, uydurma_gun", [
    # İngilizce "on" Türkçe 10 sayılmamalı; "bir ara" 1 sayılmamalı: yalnızca gün birimiyle birlikte geçerli.
    ("OOCU7710452 gated out on 21 Oct. Free time 4 days. USD 140/day.", 10),
    ("OOCU7710452 gated out 21 Oct, haftaya bir ara bakarız. Free time 4 days. USD 140/day.", 1),
])
def test_yaziyla_sayi_uydurmaya_kapi_acmaz(metin, uydurma_gun):
    with pytest.raises(AnlamHatasi, match="serbest süre"):
        anlam_kontrolu(_gate_out("OOCU7710452", "21 Oct", uydurma_gun, "belirtilmemis", 140, "gated out"),
                       _mesaj(metin))
