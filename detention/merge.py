"""Mesaj çıkarımlarını konteyner bazında birleştirip sonuç satırlarını üretir.

Akış (her konteyner için):
1. Konteyner numarası MESAJ METNİNDEN regex ile alınır (deterministik); modelin yazdığı
   numara extract.py'de buna karşı kontrol edilmiştir.
2. Seçilen formata göre doğrulama; uymayan numara hesaplanmaz, "Manuel inceleme" satırı olur.
3. Mesajlar (tarih, girdi sırası) ile sıralanır. "Çelişki varsa en son tarihli mesaj geçerli":
   - Durum (terminalden çıktı mı?) en son gate-out / terminalde mesajından,
   - Gate-out alanları (tarih, serbest süre, ücret) alan bazında en son dolu değerden,
   - İade bilgisi en son iade mesajından alınır; en son mesaj belirsizse sonuç Belirsiz olur
     (daha önce kesin tarih verilmiş olsa bile).
4. Serbest süre, detention günü, ücret, risk ve uyarı metni hesaplanır.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .calc import Kademe, detention_gun_sayisi, kademeli_ucret, risk_seviyesi, son_serbest_gun
from .container import konteyner_bul, konteyner_dogrula
from .dates import _AYNI_GUN_RE, TarihHatasi, tarih_coz, tarih_coz_detay
from .schema import CikarimSonucu, MesajCikarimi, SonucSatiri

_GUN_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def tarih_yaz(d: date | None) -> str:
    return "-" if d is None else f"{d:%d.%m.%Y} {_GUN_KISA[d.weekday()]}"


def _kisa(d: date) -> str:
    return f"{d:%d.%m}"


def _tarih_izi(ifade: str, referans: date) -> str:
    """Göreli tarih çözümünün girdisini, referansını, sonucunu ve kuralını raporlar."""
    try:
        z = tarih_coz_detay(ifade, referans)
    except TarihHatasi:
        return ""
    return (f" [tarih izi: '{z.ifade}', referans {z.referans.isoformat()} → "
            f"{z.tarih.isoformat()} ({z.kural})]")


@dataclass
class _Kayit:
    sira: int
    sonuc: CikarimSonucu

    @property
    def id(self) -> str:
        return self.sonuc.mesaj.id

    @property
    def tarih(self) -> date:
        return self.sonuc.mesaj.tarih

    @property
    def c(self) -> MesajCikarimi:
        assert self.sonuc.cikarim is not None
        return self.sonuc.cikarim


@dataclass
class _Grup:
    kayitlar: list[_Kayit] = field(default_factory=list)
    hatalar: list[str] = field(default_factory=list)   # ayrıntılı sebep (gerekçeye girer)
    kisa: list[str] = field(default_factory=list)      # kısa sebep (uyarı metnine girer)


@dataclass
class Atlanan:
    mesaj_id: str
    sebep: str


def _en_son(kayitlar: list[_Kayit]) -> _Kayit | None:
    return max(kayitlar, key=lambda k: (k.tarih, k.sira), default=None)


def _ayni_tarihli_es(kayitlar: list[_Kayit], secilen: _Kayit) -> list[_Kayit]:
    return [k for k in kayitlar if k is not secilen and k.tarih == secilen.tarih]


def _manuel(no: str, gerekce: str, kaynak: list[str], kisa: str | None = None) -> SonucSatiri:
    """`gerekce` ayrıntının tamamını taşır; uyarı 2 cümleyi geçmesin diye yalnızca `kisa` sebebi içerir."""
    return SonucSatiri(
        konteyner_no=no, son_serbest_gun=None, kalan_gun=None, planlanan_iade=None,
        tahmini_ucret_usd=None, risk="Manuel inceleme", gerekce=gerekce,
        uyari=f"{no}: otomatik hesap yapılamadı ({kisa or gerekce}). Kaydı elle kontrol edin.",
        kaynak_mesajlar=kaynak,
    )


def hesapla(
    sonuclar: list[CikarimSonucu], *, konteyner_formati: str, as_of: date
) -> tuple[list[SonucSatiri], list[Atlanan]]:
    """Ana giriş noktası. `konteyner_formati` ve `as_of` bilerek zorunlu (sessiz varsayılan yok)."""
    gruplar: OrderedDict[str, _Grup] = OrderedDict()
    atlananlar: list[Atlanan] = []

    for sira, s in enumerate(sonuclar):
        numaralar = konteyner_bul(s.mesaj.metin)
        if s.cikarim is None:
            if not numaralar:
                atlananlar.append(Atlanan(s.mesaj.id, "çıkarım başarısız ve konteyner yok: "
                                          + "; ".join(s.hatalar)))
            for no in numaralar:
                g = gruplar.setdefault(no, _Grup())
                g.hatalar.append(f"{s.mesaj.id} okunamadı ({'; '.join(s.hatalar) or 'bilinmeyen hata'})")
                g.kisa.append(f"{s.mesaj.id} mesajı doğrulanabilir biçimde okunamadı")
            continue
        if s.cikarim.mesaj_tipi == "ilgisiz":
            atlananlar.append(Atlanan(s.mesaj.id, "ilgisiz mesaj (belirli bir konteynerle ilgili değil)"))
            continue
        if len(numaralar) != 1:
            sebep = "mesajda konteyner numarası yok" if not numaralar else \
                f"mesajda birden fazla konteyner var ({', '.join(numaralar)})"
            if not numaralar:
                atlananlar.append(Atlanan(s.mesaj.id, sebep))
            for no in numaralar:
                g = gruplar.setdefault(no, _Grup())
                g.hatalar.append(f"{s.mesaj.id}: {sebep}")
                g.kisa.append(f"{s.mesaj.id} mesajında birden fazla konteyner var")
            continue
        gruplar.setdefault(numaralar[0], _Grup()).kayitlar.append(_Kayit(sira, s))

    satirlar = [_konteyner_satiri(no, g, konteyner_formati, as_of) for no, g in gruplar.items()]
    return satirlar, atlananlar


def _konteyner_satiri(no: str, g: _Grup, konteyner_formati: str, as_of: date) -> SonucSatiri:
    kaynak = sorted({k.id for k in g.kayitlar} | {h.split()[0].rstrip(":") for h in g.hatalar},
                    key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)

    gecerli, sebep = konteyner_dogrula(no, konteyner_formati)
    if not gecerli:
        return _manuel(no, f"konteyner numarası seçilen formata ({konteyner_formati}) uymuyor: {sebep}",
                       kaynak, kisa=f"konteyner numarası {konteyner_formati} formatına uymuyor")
    if g.hatalar:
        return _manuel(no, "; ".join(g.hatalar), kaynak, kisa=", ".join(g.kisa))

    durum_kayitlari = [k for k in g.kayitlar
                       if k.c.mesaj_tipi in ("gate_out_bildirimi", "terminalde_bekliyor")]
    durum = _en_son(durum_kayitlari)
    if durum is None:
        return _manuel(no, "UNKNOWN_STATUS: terminalden çıkış durumu bilinmiyor; gate-out bilgisi yok",
                       kaynak, kisa="terminalden çıkış durumu bilinmiyor")

    if durum.c.mesaj_tipi == "terminalde_bekliyor":
        return SonucSatiri(
            konteyner_no=no, son_serbest_gun=None, kalan_gun=None, planlanan_iade=None,
            tahmini_ucret_usd=None, risk="Kapsam dışı",
            gerekce=(f"Terminalden henüz çıkmamış ({durum.id}: '{durum.c.kanit}'). "
                     "Detention kapsamında değil; terminaldeki bekleme demurrage konusudur."),
            kaynak_mesajlar=kaynak,
        )

    # --- Gate-out alanları: alan bazında en son dolu değer -------------------------------
    gate_kayitlari = sorted((k for k in g.kayitlar if k.c.mesaj_tipi == "gate_out_bildirimi"),
                            key=lambda k: (k.tarih, k.sira))

    def son_dolu(alan: str) -> tuple[object, _Kayit | None]:
        for k in reversed(gate_kayitlari):
            v = getattr(k.c, alan)
            if v not in (None, []):
                return v, k
        return None, None

    gate_ifade, gate_k = son_dolu("gate_out_ifadesi")
    serbest, serbest_k = son_dolu("serbest_sure_gun")
    tip, _ = son_dolu("serbest_sure_tipi")
    kademeler_ham, ucret_k = son_dolu("ucret_kademeleri")

    if gate_ifade is None or gate_k is None:
        return _manuel(no, "gate-out tarihi mesajlarda yok", kaynak)
    try:
        gate_out = tarih_coz(str(gate_ifade), gate_k.tarih, baglam=gate_k.sonuc.mesaj.metin)
    except TarihHatasi as e:
        return _manuel(no, f"gate-out tarihi çözülemedi: {e}", kaynak)
    if serbest is None:
        return _manuel(no, "serbest süre mesajlarda yok", kaynak)

    is_gunu = tip == "is_gunu"
    son_serbest = son_serbest_gun(gate_out, int(serbest), is_gunu)
    kalan = (son_serbest - as_of).days
    tip_metni = {"is_gunu": "iş günü", "takvim": "takvim günü"}.get(
        str(tip), "gün (tip belirtilmemiş → kural gereği takvim günü)")
    gerekce = [f"Gate-out {tarih_yaz(gate_out)} ({gate_k.id}), {serbest} {tip_metni} "
               f"→ son serbest gün {tarih_yaz(son_serbest)}."
               + _tarih_izi(str(gate_ifade), gate_k.tarih)]
    kademeler = [Kademe(k.gun_sayisi, k.usd_gunluk) for k in (kademeler_ham or [])]
    gunluk_ilk = kademeler[0].usd_gunluk if kademeler else None

    # --- İade: en son iade bilgisi veren mesaj geçerli --------------------------------------
    iade_kayitlari = [k for k in g.kayitlar if k.c.iade_kesinligi != "yok"]
    iade_k = _en_son(iade_kayitlari)

    def belirsiz(neden: str) -> SonucSatiri:
        maruz = f"; gecikilen her gün ${gunluk_ilk:g}" if gunluk_ilk else ""
        if kalan < 0:
            zaman = f"son serbest gün {tarih_yaz(son_serbest)} geçti, şu an ücret işliyor"
        else:
            zaman = f"son serbest gün {tarih_yaz(son_serbest)} ({kalan} gün kaldı)"
        return SonucSatiri(
            konteyner_no=no, son_serbest_gun=son_serbest, kalan_gun=kalan, planlanan_iade=None,
            tahmini_ucret_usd=None, risk="Belirsiz",
            gerekce=" ".join(gerekce + [neden, "İade tarihi bilinmiyor; tahmin edilmedi, manuel inceleme."]),
            uyari=f"{no}: iade tarihi belirsiz, {zaman}. Kesin iade tarihini teyit edin{maruz}.",
            kaynak_mesajlar=kaynak,
        )

    if iade_k is None:
        return belirsiz("Mesajlarda iade bilgisi yok.")

    onceki = sorted((k for k in iade_kayitlari if k is not iade_k), key=lambda k: (k.tarih, k.sira))
    ezilen = ""
    if onceki:
        ezilen = (f" {iade_k.id} ({_kisa(iade_k.tarih)}) önceki iade bilgisini geçersiz kılar: "
                  + ", ".join(f"{k.id} ({_kisa(k.tarih)}, '{k.c.iade_ifadesi}')" for k in onceki) + ".")
        if _ayni_tarihli_es(iade_kayitlari, iade_k):
            ezilen += " Aynı tarihli iade mesajları var; mesaj sırası esas alındı."

    if iade_k.c.iade_kesinligi == "belirsiz":
        return belirsiz(f"{iade_k.id}: '{iade_k.c.iade_ifadesi}' bir tarih değil.{ezilen}")
    try:
        iade = tarih_coz(iade_k.c.iade_ifadesi, iade_k.tarih, baglam=iade_k.sonuc.mesaj.metin)
    except TarihHatasi as e:
        return belirsiz(f"{iade_k.id}: iade ifadesi çözülemedi ({e}).{ezilen}")
    if iade < gate_out:
        return _manuel(no, f"iade tarihi ({tarih_yaz(iade)}) gate-out'tan önce", kaynak)

    cozum = f"'{iade_k.c.iade_ifadesi}'"
    if not re.search(r"\d", iade_k.c.iade_ifadesi or ""):
        cozum += " → mesajdaki tarihe atıf" if _AYNI_GUN_RE.search(iade_k.c.iade_ifadesi.lower()) else ""
    if iade_k.c.iade_kesinligi == "goreli_gun" and not _AYNI_GUN_RE.search(iade_k.c.iade_ifadesi.lower()):
        cozum += f", mesaj tarihine ({tarih_yaz(iade_k.tarih)}) göre sonraki ilk gün"
    gerekce.append(f"İade {tarih_yaz(iade)} ({iade_k.id}: {cozum})."
                   + _tarih_izi(str(iade_k.c.iade_ifadesi), iade_k.tarih) + ezilen)

    gun = detention_gun_sayisi(son_serbest, iade)
    if gun > 0 and not kademeler:
        return _manuel(no, "detention ücreti mesajlarda yok", kaynak)
    ucret, dokum = kademeli_ucret(gun, kademeler)
    risk = risk_seviyesi(ucret, son_serbest, as_of)

    if gun == 0:
        gerekce.append(f"Serbest süre içinde iade ({(son_serbest - iade).days} gün önce), ücret yok.")
    else:
        ek = []
        if son_serbest < as_of:
            ek.append("son serbest gün geçmiş")
        if ucret >= 500:
            ek.append("≥ $500")
        kalem = " + ".join(d for d in dokum if not d.startswith("("))
        dipnot = "".join(f" {d}" for d in dokum if d.startswith("("))
        kaynak_ucret = f" [ücret: {ucret_k.id}]" if ucret_k else ""
        gerekce.append(
            f"Detention {gun} gün ({_kisa(son_serbest + timedelta(days=1))}–{_kisa(iade)}): "
            f"{kalem} = ${ucret:,.0f}" + (f" ({', '.join(ek)})" if ek else "")
            + f"{kaynak_ucret}.{dipnot}")

    uyari = None
    if risk in ("Yüksek", "Orta"):
        neden = "son serbest gün geçti" if son_serbest < as_of else \
            f"son serbest gün {tarih_yaz(son_serbest)}"
        uyari = (f"{no}: {neden}; planlanan iade {tarih_yaz(iade)} ile {gun} gün detention, "
                 f"tahmini ${ucret:,.0f}. ")
        uyari += (f"{tarih_yaz(son_serbest)} tarihine kadar iade ücreti sıfırlar; mümkün değilse "
                  "hat şirketinden serbest süre uzatımı isteyin."
                  if son_serbest >= as_of else
                  "İadeyi hızlandırın; her ek gün ücreti artırır.")

    return SonucSatiri(
        konteyner_no=no, son_serbest_gun=son_serbest, kalan_gun=kalan, planlanan_iade=iade,
        tahmini_ucret_usd=ucret, risk=risk, gerekce=" ".join(gerekce), uyari=uyari,
        kaynak_mesajlar=kaynak,
    )
