"""Deterministik katmanın testleri: konteyner, tarih, hesap ve uçtan uca beklenen tablo."""
from datetime import date

import pytest

from detention.calc import Kademe, detention_gun_sayisi, kademeli_ucret, risk_seviyesi, son_serbest_gun
from detention.container import beklenen_kontrol_hanesi, konteyner_bul, konteyner_dogrula, normalize_konteyner
from detention.dates import TarihHatasi, tarih_coz
from detention.merge import hesapla
from detention.schema import CikarimSonucu, MesajCikarimi
from detention.veri import varsayilan_as_of

AS_OF = date(2026, 10, 5)


# --- Konteyner numarası ------------------------------------------------------------------
@pytest.mark.parametrize("ham, beklenen", [
    ("MSCU4829153", "MSCU4829153"),
    ("MSCU 482915-3", "MSCU4829153"),
    ("HLCU 552018-7'nin şasisi", "HLCU5520187"),
    ("mscu-482915-3", "MSCU4829153"),
    ("Container MAEU7731042 released", "MAEU7731042"),
    ("Eylül ayı faturaları", None),
    ("USD 150/day", None),
])
def test_normalizasyon(ham, beklenen):
    assert normalize_konteyner(ham) == beklenen


def test_birden_fazla_konteyner_tekil_ve_sirali():
    assert konteyner_bul("MSCU4829153 ve MSCU 482915-3, HLCU5520187") == ["MSCU4829153", "HLCU5520187"]


def test_iso6346_bilinen_gecerli_numara():
    # ISO 6346 standardındaki örnek: CSQU3054383
    assert konteyner_dogrula("CSQU3054383", "iso6346") == (True, "ISO 6346: kontrol hanesi geçerli")


@pytest.mark.parametrize("no, yazilan, hesaplanan", [
    ("MSCU4829153", 3, 1), ("MAEU7731042", 2, 6), ("HLCU5520187", 7, 0),
    ("CMAU3301986", 6, 0), ("TGHU9004512", 2, 3), ("OOLU6612408", 8, 1),
])
def test_case_numaralari_iso_kontrol_hanesi_tutmuyor(no, yazilan, hesaplanan):
    assert int(no[10]) == yazilan and beklenen_kontrol_hanesi(no) == hesaplanan
    assert konteyner_dogrula(no, "basit")[0] is True
    assert konteyner_dogrula(no, "iso6346")[0] is False


def test_format_zorunlu():
    with pytest.raises(ValueError):
        konteyner_dogrula("MSCU4829153", "")


# --- Tarih çözümleme ---------------------------------------------------------------------
@pytest.mark.parametrize("ifade, referans, beklenen", [
    ("28 Sep 2026", date(2026, 9, 28), date(2026, 9, 28)),
    ("01 Oct", date(2026, 10, 1), date(2026, 10, 1)),
    ("30/09/2026", date(2026, 9, 30), date(2026, 9, 30)),
    ("6 Ekim'de", date(2026, 10, 2), date(2026, 10, 6)),
    ("12 Ekim'e", date(2026, 10, 4), date(2026, 10, 12)),
    ("9 Ekim Cuma", date(2026, 10, 5), date(2026, 10, 9)),
    ("perşembe", date(2026, 10, 5), date(2026, 10, 8)),      # Pzt -> Per
    ("Perşembeye", date(2026, 10, 5), date(2026, 10, 8)),    # Türkçe ek
    ("Cumartesi", date(2026, 10, 5), date(2026, 10, 10)),    # "cuma" ile karışmamalı
    ("perşembe", date(2026, 10, 8), date(2026, 10, 15)),     # perşembe yazılmışsa -> sonraki hafta
    ("Oct 8, 2026", date(2026, 10, 5), date(2026, 10, 8)),
    ("08.10.2026", date(2026, 10, 5), date(2026, 10, 8)),
    ("yarın", date(2026, 10, 5), date(2026, 10, 6)),
    ("5 Ocak", date(2026, 12, 20), date(2027, 1, 5)),        # yıl dönümü
])
def test_tarih_coz(ifade, referans, beklenen):
    assert tarih_coz(ifade, referans) == beklenen


@pytest.mark.parametrize("ifade, baglam, beklenen", [
    ("aynı gün", "MAEU7731042 boşaltması 9 Ekim Cuma bitecek, aynı gün iade.", date(2026, 10, 9)),
    ("same day", "Unloading done Oct 8, return same day.", date(2026, 10, 8)),
])
def test_ayni_gun_mesajdaki_tek_tarihe_cozulur(ifade, baglam, beklenen):
    assert tarih_coz(ifade, date(2026, 10, 5), baglam=baglam) == beklenen


@pytest.mark.parametrize("baglam", ["aynı gün iade.", "8 Ekim boşaltma, 9 Ekim kontrol, aynı gün iade."])
def test_ayni_gun_tek_tarih_yoksa_tahmin_edilmez(baglam):
    with pytest.raises(TarihHatasi):
        tarih_coz("aynı gün", date(2026, 10, 5), baglam=baglam)


@pytest.mark.parametrize("ifade", ["haftaya bir ara", "en kısa sürede", "müsait olunca", "", None,
                                   "9 Ekim Perşembe"])  # son örnek: gün adı tutarsız
def test_tarih_cozulemez(ifade):
    with pytest.raises(TarihHatasi):
        tarih_coz(ifade, date(2026, 10, 5))


# --- Hesap ---------------------------------------------------------------------------------
def test_takvim_gunu():
    assert son_serbest_gun(date(2026, 9, 28), 5, is_gunu=False) == date(2026, 10, 3)


def test_is_gunu_hafta_sonunu_atlar():
    # 01.10 Per gate-out -> 2 Cum, 5 Pzt, 6 Sal, 7 Çar
    assert son_serbest_gun(date(2026, 10, 1), 4, is_gunu=True) == date(2026, 10, 7)


def test_detention_gunleri_iade_gunu_dahil():
    assert detention_gun_sayisi(date(2026, 10, 3), date(2026, 10, 8)) == 5
    assert detention_gun_sayisi(date(2026, 10, 13), date(2026, 10, 8)) == 0


def test_kademeli_ucret():
    assert kademeli_ucret(5, [Kademe(3, 120), Kademe(None, 200)])[0] == 760
    assert kademeli_ucret(2, [Kademe(3, 120), Kademe(None, 200)])[0] == 240
    assert kademeli_ucret(5, [Kademe(None, 150)])[0] == 750
    assert kademeli_ucret(0, [])[0] == 0


@pytest.mark.parametrize("ucret, son_serbest, beklenen", [
    (None, date(2026, 10, 7), "Belirsiz"),
    (200, date(2026, 10, 7), "Orta"),
    (200, date(2026, 10, 3), "Yüksek"),       # son serbest gün geçmiş
    (500, date(2026, 10, 7), "Yüksek"),       # eşik dahil
    (0, date(2026, 10, 3), "Düşük"),
    (100, date(2026, 10, 5), "Orta"),         # son gün bugün: henüz geçmedi
])
def test_risk(ucret, son_serbest, beklenen):
    assert risk_seviyesi(ucret, son_serbest, AS_OF) == beklenen


# --- Uçtan uca (modelin doğru çıktısıyla) ----------------------------------------------------
BEKLENEN_TABLO = {
    #  no             son serbest          kalan  iade                ücret  risk
    "MSCU4829153": (date(2026, 10, 3), -2, date(2026, 10, 8), 750.0, "Yüksek"),
    "MAEU7731042": (date(2026, 10, 7), 2, date(2026, 10, 9), 200.0, "Orta"),
    "HLCU5520187": (date(2026, 10, 7), 2, date(2026, 10, 12), 760.0, "Yüksek"),
    "CMAU3301986": (date(2026, 10, 7), 2, None, None, "Belirsiz"),
    "TGHU9004512": (date(2026, 10, 13), 8, date(2026, 10, 8), 0.0, "Düşük"),
    "OOLU6612408": (None, None, None, None, "Kapsam dışı"),
}


def test_as_of_en_son_mesaj_tarihi(mesajlar):
    assert varsayilan_as_of(mesajlar) == AS_OF


def test_case_beklenen_tablo(altin_sonuclar):
    satirlar, atlananlar = hesapla(altin_sonuclar, konteyner_formati="basit", as_of=AS_OF)
    sonuc = {s.konteyner_no: (s.son_serbest_gun, s.kalan_gun, s.planlanan_iade,
                              s.tahmini_ucret_usd, s.risk) for s in satirlar}
    assert sonuc == BEKLENEN_TABLO
    assert [a.mesaj_id for a in atlananlar] == ["M13"]


def test_m7_m4u_gecersiz_kilar_ve_gerekcede_yazar(altin_sonuclar):
    satirlar, _ = hesapla(altin_sonuclar, konteyner_formati="basit", as_of=AS_OF)
    hlcu = next(s for s in satirlar if s.konteyner_no == "HLCU5520187")
    assert "M7" in hlcu.gerekce and "M4" in hlcu.gerekce and "geçersiz kılar" in hlcu.gerekce
    assert hlcu.kaynak_mesajlar == ["M3", "M4", "M7"]


def test_uyari_sadece_riskli_konteynerlerde(altin_sonuclar):
    satirlar, _ = hesapla(altin_sonuclar, konteyner_formati="basit", as_of=AS_OF)
    uyarili = {s.konteyner_no for s in satirlar if s.uyari}
    assert uyarili == {"MSCU4829153", "MAEU7731042", "HLCU5520187", "CMAU3301986"}


def test_iso6346_secilirse_hepsi_manuel_incelemeye(altin_sonuclar):
    satirlar, _ = hesapla(altin_sonuclar, konteyner_formati="iso6346", as_of=AS_OF)
    assert {s.risk for s in satirlar} == {"Manuel inceleme"}
    mscu = next(s for s in satirlar if s.konteyner_no == "MSCU4829153")
    assert "yazılan 3, hesaplanan 1" in mscu.gerekce


def test_bugunun_tarihi_kullanilsaydi_maeu_yuksek_olurdu(altin_sonuclar):
    satirlar, _ = hesapla(altin_sonuclar, konteyner_formati="basit", as_of=date(2026, 11, 15))
    assert next(s for s in satirlar if s.konteyner_no == "MAEU7731042").risk == "Yüksek"


def test_en_son_mesaj_belirsizse_sonuc_belirsiz(mesajlar, beklenen_cikarim, altin_sonuclar):
    # TGHU için M8'den (8 Ekim) sonra belirsiz bir mesaj gelirse, kural gereği sonuç Belirsiz.
    from detention.schema import Mesaj
    yeni = Mesaj(id="M14", tarih=date(2026, 10, 5), gonderen="Depo",
                 metin="TGHU9004512 araç bulunamadı, iade müsait olunca.")
    c = dict(beklenen_cikarim["M11"], konteyner_no_ham="TGHU9004512",
             iade_ifadesi="müsait olunca", kanit="iade müsait olunca")
    sonuclar = altin_sonuclar + [CikarimSonucu(mesaj=yeni, cikarim=MesajCikarimi.model_validate(c))]
    satirlar, _ = hesapla(sonuclar, konteyner_formati="basit", as_of=AS_OF)
    assert next(s for s in satirlar if s.konteyner_no == "TGHU9004512").risk == "Belirsiz"


def test_okunamayan_mesaj_manuel_incelemeye(altin_sonuclar):
    bozuk = altin_sonuclar[:]
    bozuk[9] = CikarimSonucu(mesaj=bozuk[9].mesaj, cikarim=None, hatalar=["kanit mesajda yok"])  # M10
    satirlar, _ = hesapla(bozuk, konteyner_formati="basit", as_of=AS_OF)
    maeu = next(s for s in satirlar if s.konteyner_no == "MAEU7731042")
    assert maeu.risk == "Manuel inceleme" and "M10" in maeu.gerekce


# --- Uyarı metni: case "1-2 cümle" istiyor ---------------------------------------------------
def _cumle_sayisi(metin: str) -> int:
    import re
    t = re.sub(r"\d{2}\.\d{2}\.\d{4}", "TARIH", metin)
    return len([x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x])


def test_tum_uyarilar_en_fazla_iki_cumle(altin_sonuclar):
    bozuk = altin_sonuclar[:]
    bozuk[9] = CikarimSonucu(mesaj=bozuk[9].mesaj, cikarim=None, hatalar=[   # M10: gerçek ret metni
        "deneme 1: mesaj_tipi 'gate_out_bildirimi' denmiş ama mesajda gate-out ifadesi yok (gated out / "
        "picked up / released). Unloading (boşaltma) is not gate-out; a message about returning the "
        "container is iade_plani", "deneme 2: iade_ifadesi 'x' cannot be resolved to a date from this "
        "message; if no date is given, use iade_kesinligi 'belirsiz'"])
    for sonuclar, fmt in [(altin_sonuclar, "basit"), (altin_sonuclar, "iso6346"), (bozuk, "basit")]:
        satirlar, _ = hesapla(sonuclar, konteyner_formati=fmt, as_of=AS_OF)
        uyarilar = [s.uyari for s in satirlar if s.uyari]
        assert uyarilar
        for u in uyarilar:
            assert 1 <= _cumle_sayisi(u) <= 2, u
            assert len(u) < 260, u


def test_manuel_uyarisi_kisa_gerekce_ayrintili(altin_sonuclar):
    bozuk = altin_sonuclar[:]
    bozuk[9] = CikarimSonucu(mesaj=bozuk[9].mesaj, cikarim=None, hatalar=["deneme 1: ham ret metni. İkinci cümle."])
    satirlar, _ = hesapla(bozuk, konteyner_formati="basit", as_of=AS_OF)
    maeu = next(s for s in satirlar if s.konteyner_no == "MAEU7731042")
    assert "ham ret metni" in maeu.gerekce            # ayrıntı gerekçede kalır
    assert "ham ret metni" not in maeu.uyari          # uyarıya girmez
    assert "M10" in maeu.uyari
