# Konteyner Detention Risk Analizi

Hat şirketleri, sürücüler ve depolardan gelen yapılandırılmamış operasyon mesajlarını okuyup konteyner
başına detention riskini hesaplar. Yerel dil modeli mesajlardan yapılandırılmış bilgi çıkarır; tarih ve ücret
hesabı Python kodunda yapılır. Çalışma sırasında harici bir model API'si kullanılmaz.

## Tasarım yaklaşımı

Sistem, dil modelinin güçlü olduğu işi kuralların gerektirdiği kesinlikten ayırma ilkesine göre tasarlanmıştır.

- **Model yalnızca okur.** Mesajı bir türe ayırır ve alanları metinde yazıldığı haliyle kopyalar
  ("perşembe", "12 Ekim'e", "USD 150/day"). Tarih aritmetiği, gün sayımı ve ücret hesabı yapmaz.
- **Hesaplamanın tamamı deterministik koddadır.** Aynı mesajlar ve aynı hesap tarihi aynı hesabı üretir;
  kurallar kodda ayrı ayrı test edilir. Yeni bir hesaplama kuralı eklemek modele dokunmayı gerektirmez.
- **Belirsizlik tahminle doldurulmaz.** Kesin tarihe çevrilemeyen bir ifade ("haftaya bir ara") "bilinmiyor"
  olarak işaretlenir.
- **Hata güvenli tarafa düşer.** Model çıktısı doğrulanamazsa kayıt yanlış bir değer üretmek yerine
  "Manuel inceleme" olarak raporlanır.

## Uçtan uca akış

```
mesaj ─► Yerel LLM: sınıflandırma + metinden ham alanları çıkarma
      ─► JSON Schema/grammar → Pydantic → kanıt ve anlam kontrolleri
      ─► Hatalıysa geri bildirimle bir kez yeniden deneme; yine başarısızsa manuel inceleme
      ─► Konteyner başına, alan bazında birleştirme ve kaynak mesaj takibi
      ─► Durum değerlendirmesi: gate-out / açıkça terminalde / bilinmeyen
      ─► Deterministik tarih çözümü → serbest süre → detention ücreti → risk ve uyarı
```

## Deterministik kodda kalan kararlar

| Karar | Uygulama | Modül |
|---|---|---|
| Konteyner numarası | Regex ile `XXXX1234567` biçimine normalizasyon ("MSCU 482915-3" dahil); seçilebilir doğrulama: `basit` veya ISO 6346 kontrol hanesi. Numara hiçbir zaman otomatik düzeltilmez | `container.py` |
| Tarih çözümleme | Türkçe ve İngilizce açık/göreli tarihler; ISO hafta kuralları ve çözüm izi | `dates.py` |
| Serbest süre | Gate-out'un ertesi günü başlar; iş günü ise hafta sonları atlanır, aksi halde takvim günü sayılır | `calc.py` |
| Detention ücreti | Son serbest günden sonraki günden iade günü dahil; kademeli tarifeler desteklenir | `calc.py` |
| Çelişkili bilgi | Alanlar ayrı ayrı birleştirilir; her alanda en son açık bilgi geçerlidir. Eşit tarihte girdi sırası kullanılır | `merge.py` |
| Kapsam | Terminalden çıkmamış konteyner detention kapsamı dışındadır (demurrage); konteynerle ilgisi olmayan mesajlar atlanır | `merge.py` |
| Risk seviyesi | Yüksek / Orta / Düşük / Belirsiz eşikleri | `calc.py` |
| Uyarı metni | Kod şablonundan üretilir (en fazla iki cümle); ücret hesabı raporda yeniden yapılmaz | `merge.py` |

## Model çıktısının güvencesi

1. **Kısıtlı üretim:** Pydantic şeması `response_format: json_schema` ile llama.cpp'ye verilir; destekleyen
   sunucu şemadan grammar türetip uyumsuz token'ları üretim sırasında kısıtlar. Bu, biçim hatalarını azaltır;
   semantik doğruluk garantisi değildir.
2. **Tip doğrulaması:** Pydantic (`extra="forbid"`; tüm alanlar zorunlu, bilinmeyen değer için açıkça `null`).
3. **Anlam kontrolü:** Sınıflandırma kanıtı ve tarih ifadeleri mesajda aranır; konteyner numarası mesajdan
   bulunan numarayla karşılaştırılır; ücret ve gün sayılarının mesajda bulunması denetlenir. Bu kontroller
   yanlış ilişkilendirmelerin tümünü kanıtlayamaz; doğrulanamayan çıktılar reddedilir.
4. **Yeniden deneme:** Reddedilen çıktının sebebi modele geri bildirilir; ikinci deneme de başarısız olursa
   kayıt manuel incelemeye düşer.

## Model seçimi

**Qwen3.5-4B, Q4_K_M GGUF** (`unsloth/Qwen3.5-4B-GGUF`, 2,74 GB) — llama.cpp `llama-server` (b12014),
Metal GPU, düşünme (thinking) modu kapalı, temperature 0.

- **Boyut:** Görev kısa ve iki dilli mesajlardan birkaç alan çıkarmak ve dört sınıftan birini seçmektir;
  hesaplama kodda olduğundan 4B parametre yeterlidir. 2B sınıfı modeller ölçümde yetersiz kalmıştır.
- **Quantization:** Q6_K, Q4_K_M'ye göre daha büyük ve yavaş olup doğrulukta kazanç sağlamamıştır.
- **Donanım:** Apple M2, 16 GB birleşik bellek. Ölçülen bellek kullanımı yaklaşık 3,4 GB
  (sunucu süreci 0,68 GB + belleğe eşlenen 2,74 GB model dosyası).
- **Gecikme:** Mesaj başına medyan 5,4–7,2 sn, saniyede 18–26 token (adaptör takılıyken). Sabit prompt öneki
  sunucuda önbelleğe alınır; süreyi büyük ölçüde çıktı uzunluğu belirler.
- **Runtime:** llama.cpp, JSON şemasından grammar üreterek çıktıyı üretim sırasında kısıtlayabildiği için seçilmiştir.

40 etiketli mesaj (13 örnek mesaj ve 27 varyasyon) üzerinde yapılan karşılaştırma:

| Model | Dosya | Alan doğruluğu | Manuel inceleme | Örnek senaryo (6 konteyner) | Medyan sn |
|---|---|---|---|---|---|
| **Qwen3.5-4B Q4_K_M** | 2,74 GB | **%90,0** | **3** | **6/6** | 5,4 |
| Qwen3.5-4B Q6_K | 3,53 GB | %87,8 | 4 | 6/6 | 7,0 |
| Qwen3.5-2B Q4_K_M | 1,28 GB | %77,5 | 7 | 4/6 | 4,2 |
| Gemma 4 E4B-it Q4_K_M | 5,41 GB | %85,6 | 5 | 6/6 | 8,6 |
| Gemma 4 E2B-it Q4_K_M | 3,46 GB | %80,0 | 7 | 4/6 | 4,6 |

Doğrulama kurallarındaki sonraki bir çalıştırmada seçilen model için aynı veri setinde %94,7 alan doğruluğu ve
1 manuel inceleme kaydedilmiştir. Bunlar küçük, varyasyonları bağımsız olmayan veri kümesinin ölçümüdür;
genel saha başarısı olarak yorumlanmamalıdır. Veri seti `bench/dataset.py`, ham sonuçlar `bench/results/`.

## Kurulum

Gereksinimler: Apple Silicon Mac, Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
# 1. Python bağımlılıkları
uv sync

# 2. llama.cpp (hazır derlenmiş macOS arm64 paketi)
mkdir -p vendor/llama-b12014 && cd vendor/llama-b12014
curl -sSLO https://github.com/ggml-org/llama.cpp/releases/download/b12014/llama-b12014-bin-macos-arm64.tar.gz
echo "f787dac1e0f25fe103172a889d20498aee974147c077d30cc144671b0ad04ad8  llama-b12014-bin-macos-arm64.tar.gz" | shasum -a 256 -c -
tar -xzf llama-b12014-bin-macos-arm64.tar.gz && cd ../..

# 3. Model (2,74 GB); farklı bir konum için DETENTION_MODEL_PATH ortam değişkeni kullanılabilir
mkdir -p ~/case2/models/qwen3.5-4b
curl -L -o ~/case2/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf \
  https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf
echo "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4  $HOME/case2/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf" | shasum -a 256 -c -
```

## Kullanım

```bash
./scripts/start_server.sh                                  # model sunucusu (yalnızca 127.0.0.1)
uv run python scripts/smoke_test.py                        # sunucu, şema ve thinking kontrolü
uv run python run.py --konteyner-formati basit             # mesajları canlı modelle işler
uv run python run.py --konteyner-formati basit --offline   # kayıtlı model çıktılarıyla, sunucu gerektirmez
uv run python run.py --konteyner-formati basit --altin     # modelsiz; yalnızca deterministik katman
```

- `--konteyner-formati` (`basit` | `iso6346`) bilinçli olarak varsayılansız bırakılmıştır; verilmezse sorulur.
- `--as-of` verilmezse canlı kullanım bugünün tarihini, `--offline` ve `--altin` ise veri kümesinin
  en son mesaj tarihini kullanır. Tekrarlanabilir çalıştırmalar için tarihi açıkça `--as-of YYYY-MM-DD`
  ile verin; seçilen tarih JSON metadata'sına yazılır.
- Çıktılar: konsol tablosu, gerekçeler ve uyarılar; ayrıca `out/results.json` ve `out/results.csv`.

## Örnek çıktı

`data/messages.json` içindeki 13 mesaj için (hesap tarihi 05.10.2026, format `basit`):

| konteyner_no | son_serbest_gun | kalan_gun | planlanan_iade | tahmini_ucret_usd | risk |
|---|---|---|---|---|---|
| MSCU4829153 | 03.10.2026 | -2 | 08.10.2026 | $750 | Yüksek |
| MAEU7731042 | 07.10.2026 | 2 | 09.10.2026 | $200 | Orta |
| HLCU5520187 | 07.10.2026 | 2 | 12.10.2026 | $760 | Yüksek |
| CMAU3301986 | 07.10.2026 | 2 | bilinmiyor | - | Belirsiz |
| TGHU9004512 | 13.10.2026 | 8 | 08.10.2026 | $0 | Düşük |
| OOLU6612408 | - | - | - | - | Kapsam dışı |

Fatura bildirimi içeren mesaj, konteynerle ilgisi olmadığı için raporda "atlanan mesajlar" altında listelenir.

## Testler

```bash
uv run pytest -q          # birim ve gold senaryosu testleri; model gerektirmez
uv run pytest -m live -q  # gerçek modelle uçtan uca testler (sunucu açıkken)
```

## Birleştirme, kanıt ve durum

- Mesajlar konteyner başına alan bazında birleştirilir. Gate-out tarihi, serbest süre türü/sayısı ve ücret
  kademeleri ayrı ayrı en son açık değerden alınır; iade planı bunlardan bağımsız güncellenir.
- Her seçilen alanın mesaj kimliği gerekçede veya kaynak mesajlar listesinde yer alır. Önceki iade
  bildirimleri korunur ve yeni bildirimle geçersiz kılındıkları gerekçede gösterilir. Eşit mesaj tarihlerinde
  girdi sırası kullanılır; sonraki satır önceliklidir.
- Modelin kısa `kanit` alıntısı orijinal metinde aranır; bu alıntı mesaj türünü destekler. Konteyner
  numarası metinden deterministik çıkarılıp normalize edilmiş değerle karşılaştırılır; tarih ham ifade
  olarak kalır ve `dates.py` çözer.
  Sayıların mesajda bulunması doğrulanır. JSON Schema yalnızca biçimi, Pydantic ise biçim ve tipleri garanti
  eder; doğru anlamı tek başına garanti etmez. Anlam kontrolleri bunu ek olarak denetler.
- Gate-out mesajı varsa konteyner detention değerlendirmesine alınır. `terminalde_bekliyor` açıkça
  bildirildiyse detention kapsamı dışı raporlanır. Bu iki durumdan hiçbiri yoksa `UNKNOWN_STATUS` olur ve
  manuel incelemeye gider; iade planı tek başına gate-out sayılmaz. Bunlar ayrı enum değerleri değil, mevcut
  mesaj türlerinden türetilen durum yorumlarıdır.
- Manuel inceleme gerekçeleri şu anda açıklayıcı metinle raporlanır: eksik gate-out, bilinmeyen durum,
  çözülemeyen tarih, çıkarım doğrulama hatası veya geçersiz konteyner numarası. Ayrı standart neden kodları
  ve model destekli tarih yedek çözümlemesi henüz uygulanmadı.

## Göreli tarih çözümleme

`dates.py` önce açıkça tanımlı deterministik kuralları uygular; LLM yalnızca mesajdaki ham ifadeyi çıkarır.
`tarih_coz_detay` orijinal ifadeyi, mesaj tarihini referans olarak, çözümlenen tarihi ve kullanılan kuralı
taşır. Rapor gerekçesine göreli tarih için bu iz eklenir. Tarih hesabında sistem saati kullanılmaz.

- Türkçe: bugün, yarın, öbür gün, dün, önceki gün, `N gün sonra/önce`, bu hafta + gün adı, haftaya bugün,
  haftaya/gelecek hafta/önümüzdeki hafta + gün adı, iki hafta sonra bugün/gün adı, gelecek ayın 5'i,
  ayın son günü ve önümüzdeki hafta sonu.
- İngilizce: today, tomorrow, the day after tomorrow, yesterday, `in N days`, `N days ago`, next + weekday,
  weekday next week, this + weekday, a week from today, two weeks from today, end of next week ve next weekend.
- ISO haftası Pazartesi başlar. Yalın `Perşembe`, referans tarihinden sonraki ilk Perşembe olur (referans
  zaten Perşembe ise sonraki haftaya geçer). `Haftaya Perşembe` gelecek ISO haftasındaki Perşembe;
  `Haftaya bugün` ise referans tarihinden tam 7 gün sonrasıdır.
- `haftaya bir ara`, `sometime next week` ve tanınmayan biçimler tahmin edilmez; tarih manuel incelemede
  bilinmiyor kalır. Yalın `haftaya` gün belirtmediği için belirsizdir.
- Girdi şeması mesaj tarihini saat dilimi olmayan `date` olarak tutar. Saat dilimli kaynak timestamp'i varsa
  onu mesajın yerel takvim tarihine dönüştürüp bu alana vermek gerekir; bu projede kaynak timestamp'i veya
  saat dilimi bilgisi bulunmadığından saat dilimi dönüşümü yapılmaz.

## Benchmark ve kapsam

`bench/dataset.json` 40 etiketli örnek içerir: 13 case mesajı, 7 yoklama ve 20 varyasyon. Varyasyonlar
bağımsız saha verisi değildir ve orijinal kalıplara benzer; bu nedenle mevcut doğruluk sonuçları
genellenebilir performans iddiası olarak okunmamalıdır. Şu an benchmark tüm örneklerde alan doğruluğu,
mesaj tipi, iade tarihi, şema geçerliliği, manuel inceleme ve 13 mesajlık case uçtan uca sonucunu raporlar.
Kaynak/grup bazlı ayrılmış bağımsız test kümesi ve container ID, gate-out, free time, detention rate,
false negative gibi ayrı metrikler henüz eklenmedi. Önceden kaydedilmiş sonuç dosyaları değiştirilmemiştir.

## Varsayımlar ve sınırlamalar

- Gün adı ("perşembe") mesaj tarihinden sonraki ilk o güne çözülür; hafta kaydırıcısı gelecek takvim
  haftasını belirtir; yıl belirtilmemişse mesajın yılı alınır;
  sayısal tarihler gün/ay sırasıyla okunur; "aynı gün" mesajda geçen tek tarihe bağlanır.
- İş günü hesabında yalnızca hafta sonları atlanır; resmi tatiller dikkate alınmaz.
- Model "boşaltma" bildirimlerini ilk denemede gate-out olarak sınıflandırma eğilimindedir; anlam kontrolü bunu
  yakalar ve doğru sonuç yeniden denemeyle elde edilir.
- Gate-out tespiti bir ifade listesine dayanır; listede bulunmayan bir ifade manuel incelemeye düşer.
- Birden fazla tarih içeren "aynı gün" ifadeleri ve tek mesajda birden fazla konteyner otomatik işlenmez.
- Mesaja gömülü talimatlar (prompt injection) modeli etkileyebilir; anlam kontrolü bu durumu yakalayarak
  kaydı manuel incelemeye yönlendirir.

## Proje yapısı

```
detention/   çekirdek kod (container, dates, calc, merge, schema, prompt, llm, extract, report)
data/        örnek mesajlar ve yoklama mesajları
tests/       birim ve uçtan uca testler
scripts/     sunucu başlatma, duman testi, yoklama
cache/       kayıtlı model çıktıları (--offline)
bench/       model karşılaştırması: veri seti, ölçüm betikleri, sonuçlar
run.py       komut satırı arayüzü
```
