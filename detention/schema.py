"""Pydantic şemaları.

MesajCikarimi: LLM'in her mesaj için üreteceği JSON. Bu şema llama-server'a
`response_format: json_schema` ile verilir; runtime şemadan bir grammar (GBNF) türetir
ve şemaya uymayan token'ları üretim sırasında maskeler. Yani biçim üretim anında garanti
edilir; Pydantic bunu ikinci kez doğrular, anlam kontrolü ise extract.py'de yapılır.

Tasarım kararları:
- Her alan ZORUNLU ama null olabilir (varsayılan değer yok). Varsayılanlı alan `required`
  listesine girmez ve grammar o alanı atlamaya izin verir; böylece model her anahtarı yazar,
  bilmediğinde açıkça null yazar.
- extra="forbid" -> şemada additionalProperties: false, uydurma alan üretilemez.
- Alan sırası üretim sırasıdır: önce kısa kanıt ve mesaj tipi, sonra ayrıntılar.
- Model hesap YAPMAZ: tarihler metindeki ham ifade olarak gelir, kod çözer.
- String alanlara makul maxLength verildi (döngüye giren üretimi keser). Çok büyük
  maxLength llama.cpp'de geçersiz grammar üretebildiği için küçük tutuldu.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

KisaMetin = Annotated[str, Field(max_length=80)]

MesajTipi = Literal["gate_out_bildirimi", "iade_plani", "terminalde_bekliyor", "ilgisiz"]
SerbestSureTipi = Literal["takvim", "is_gunu", "belirtilmemis"]
IadeKesinligi = Literal["kesin_tarih", "goreli_gun", "belirsiz", "yok"]


class UcretKademesi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gun_sayisi: int | None  # None = "thereafter" ya da tek sabit ücret
    usd_gunluk: float


class MesajCikarimi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kanit: Annotated[str, Field(max_length=160)]  # mesajdan birebir en kısa alıntı
    mesaj_tipi: MesajTipi
    konteyner_no_ham: KisaMetin | None  # yazıldığı gibi, düzeltmeden
    gate_out_ifadesi: KisaMetin | None  # "28 Sep 2026", "01 Oct"
    serbest_sure_gun: int | None
    serbest_sure_tipi: SerbestSureTipi | None
    ucret_kademeleri: Annotated[list[UcretKademesi], Field(max_length=5)]
    iade_ifadesi: KisaMetin | None  # "6 Ekim'de", "perşembe", "haftaya bir ara"
    iade_kesinligi: IadeKesinligi


class Mesaj(BaseModel):
    """Girdi mesajı (data/messages.json satırı)."""

    id: str
    tarih: date
    gonderen: str
    metin: str


class CikarimSonucu(BaseModel):
    """Bir mesajın çıkarım sonucu. `cikarim` None ise doğrulama tüm denemelerde başarısız oldu."""

    mesaj: Mesaj
    cikarim: MesajCikarimi | None
    hatalar: list[str] = []
    deneme: int = 0
    sure_sn: float | None = None


Risk = Literal["Yüksek", "Orta", "Düşük", "Belirsiz", "Kapsam dışı", "Manuel inceleme"]


class SonucSatiri(BaseModel):
    """Case'in istediği çıktı alanları + izlenebilirlik için kaynak mesajlar ve uyarı."""

    model_config = ConfigDict(extra="forbid")
    konteyner_no: str
    son_serbest_gun: date | None
    kalan_gun: int | None  # son serbest gün - hesap tarihi; negatif = geçmiş
    planlanan_iade: date | None  # None = bilinmiyor
    tahmini_ucret_usd: float | None  # None = hesaplanamadı / bilinmiyor
    risk: Risk
    gerekce: str
    uyari: str | None = None
    kaynak_mesajlar: list[str] = []
