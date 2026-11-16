# Konteyner Detention Risk Analizi (Lokal LLM)

Hat şirketleri, sürücüler ve depolardan gelen yapılandırılmamış operasyon mesajlarını okuyarak her konteyner
için detention (gecikme) riskini hesaplayan bir sistemdir. Dil modeli Hugging Face'ten indirilip tamamen yerel
olarak çalıştırılır; harici bir API kullanılmaz.

## Tasarım yaklaşımı

Sistem, dil modelinin güçlü olduğu işi kuralların gerektirdiği kesinlikten ayırma ilkesine göre tasarlanmıştır.

- **Model yalnızca okur.** Mesajı bir türe ayırır ve alanları metinde yazıldığı haliyle kopyalar
  ("perşembe", "12 Ekim'e", "USD 150/day"). Tarih aritmetiği, gün sayımı ve ücret hesabı yapmaz.
- **Hesaplamanın tamamı deterministik koddadır.** Aynı girdi her zaman aynı sonucu üretir ve her kural ayrı
  ayrı test edilir. Yeni bir kural eklemek modele dokunmayı gerektirmez.
- **Belirsizlik tahminle doldurulmaz.** Kesin tarihe çevrilemeyen bir ifade ("haftaya bir ara") "bilinmiyor"
  olarak işaretlenir.
- **Hata güvenli tarafa düşer.** Model çıktısı doğrulanamazsa kayıt yanlış bir değer üretmek yerine
  "Manuel inceleme" olarak raporlanır.

## Mimari

```
mesaj ─► Dil modeli: mesaj türü + alanların metindeki hali
      ─► Doğrulama: JSON şeması (kısıtlı üretim) → Pydantic → metne karşı anlam kontrolü
         doğrulanamazsa hata geri bildirimiyle 1 yeniden deneme → yine olmazsa "Manuel inceleme"
      ─► Deterministik katman: konteyner no → tarih çözümleme → birleştirme → ücret → risk → uyarı metni
```

## Deterministik kodda kalan kararlar

| Karar | Uygulama | Modül |
|---|---|---|
| Konteyner numarası | Regex ile `XXXX1234567` biçimine normalizasyon ("MSCU 482915-3" dahil); seçilebilir doğrulama: `basit` veya ISO 6346 kontrol hanesi. Numara hiçbir zaman otomatik düzeltilmez | `container.py` |
| Tarih çözümleme | Türkçe ve İngilizce ay/gün adları, Türkçe ekler, sayısal tarihler, "yarın", "aynı gün"; göreli ifadeler mesaj tarihine göre çözülür | `dates.py` |
| Serbest süre | Gate-out'un ertesi günü başlar; iş günü ise hafta sonları atlanır, aksi halde takvim günü sayılır | `calc.py` |
| Detention ücreti | Son serbest günden sonraki günden iade günü dahil; kademeli tarifeler desteklenir | `calc.py` |
| Çelişkili bilgi | Aynı konteyner için en son tarihli mesaj geçerlidir; geçersiz kılınan mesajlar gerekçede belirtilir | `merge.py` |
| Kapsam | Terminalden çıkmamış konteyner detention kapsamı dışındadır (demurrage); konteynerle ilgisi olmayan mesajlar atlanır | `merge.py` |
| Risk seviyesi | Yüksek / Orta / Düşük / Belirsiz eşikleri | `calc.py` |
| Uyarı metni | Şablondan üretilir (en fazla iki cümle); modelin uydurma bir rakam yazma olasılığı yoktur | `merge.py` |

## Model çıktısının güvencesi

1. **Kısıtlı üretim:** Pydantic şeması `response_format: json_schema` ile llama.cpp'ye verilir; sunucu şemadan
   bir grammar türetir ve şemaya uymayan token'ları üretim sırasında maskeler. Geçersiz JSON üretilemez.
2. **Tip doğrulaması:** Pydantic (`extra="forbid"`; tüm alanlar zorunlu, bilinmeyen değer için açıkça `null`).
3. **Anlam kontrolü:** Her değer mesaj metnine karşı denetlenir: alıntılar ve tarih ifadeleri metinde geçmeli,
   ücret ve gün sayıları metinde bulunmalı, konteyner numarası regex sonucuyla eşleşmeli, sınıf metindeki
   kanıtla tutarlı olmalıdır.
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

Doğrulama kurallarındaki son iyileştirmelerin ardından seçilen modelle aynı veri seti üzerinde alan doğruluğu
%94,7'ye yükselmiş, manuel incelemeye düşen kayıt sayısı 1'e inmiştir. Örneklem küçük olduğundan bir-iki
mesajlık farklar anlamlı kabul edilmemelidir. Veri seti `bench/dataset.py`, ham sonuçlar `bench/results/`.

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
- `--as-of` verilmezse hesap tarihi en son mesajın tarihidir; canlı kullanımda güncel tarih verilmelidir.
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
uv run pytest -q          # 84 test, model gerektirmez
uv run pytest -m live -q  # gerçek modelle uçtan uca testler (sunucu açıkken)
```

## Varsayımlar ve sınırlamalar

- Gün adı ("perşembe") mesaj tarihinden sonraki ilk o güne çözülür; yıl belirtilmemişse mesajın yılı alınır;
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
