#!/usr/bin/env bash
# Gece benchmark'ı: her model için (gerekirse yer aç) -> indir -> sunucu -> ölç -> kapat.
# Kullanım: ./bench/run_all.sh baslat
# Modeller proje içindeki models_bench/ klasörüne iner; yer yetmezse yalnızca o klasördeki en eski
# benchmark modeli silinir (delete_model.sh). Mevcut Qwen3.5-4B Q4_K_M dosyasına yalnızca okumak için erişilir.
set -uo pipefail
KOK="$(cd "$(dirname "$0")/.." && pwd)" || exit 1
cd "$KOK" || exit 1
mkdir -p bench/results models_bench
LOG="bench/results/run_all.log"
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
caffeinate -dims -w $$ &

uv run python bench/dataset.py >> "$LOG" 2>&1 || { log "dataset hatası"; exit 1; }
PAY_KB=$((3 * 1024 * 1024))   # indirmeden sonra en az 3 GB boş kalsın

yer_ac() {  # $1 gereken bayt, $2 korunacak dosya adı
  local gerek_kb=$(( $1 / 1024 + PAY_KB )) eski
  while (( $(df -k "$KOK" | awk 'NR==2{print $4}') < gerek_kb )); do
    eski=$(ls -tr models_bench/*.gguf 2>/dev/null | grep -v "/$2\$" | head -1)
    [ -z "$eski" ] && return 1
    log "yer açılıyor: $(basename "$eski") siliniyor"
    ./bench/delete_model.sh "$(basename "$eski")" >> "$LOG" 2>&1
  done
}

calistir() {  # $1 ad, $2 gguf yolu
  local ad="$1" yol="$2" hazir=0
  pkill -f llama-server; sleep 3
  log "$ad: sunucu başlatılıyor"
  ./scripts/start_server.sh "$yol" 8080 > "bench/results/server_$ad.log" 2>&1 &
  for _ in $(seq 1 90); do
    curl -s -m 2 http://127.0.0.1:8080/health | grep -q '"ok"' && { hazir=1; break; }
    sleep 2
  done
  if (( ! hazir )); then log "$ad: sunucu açılmadı (bkz. bench/results/server_$ad.log)"; pkill -f llama-server; return; fi
  log "$ad: ölçüm başlıyor"
  uv run python bench/run_bench.py --model-adi "$ad" --model-yolu "$yol" >> "$LOG" 2>&1 || log "$ad: run_bench hata kodu $?"
  pkill -f llama-server
  log "$ad: bitti; 60 sn soğuma"
  sleep 60
}

indir_calistir() {  # $1 ad, $2 repo, $3 dosya, $4 sha256, $5 boyut
  if [ ! -f "models_bench/$3" ]; then   # zaten inmişse yer açmaya ve indirmeye gerek yok
    yer_ac "$5" "$3" || { log "$1: yeterli yer açılamadı, atlandı"; return; }
    log "$1: indiriliyor ($3, $(( $5 / 1000000 )) MB)"
  fi
  ./bench/download_model.sh "$2" "$3" "$4" "$5" >> "$LOG" 2>&1 || { log "$1: indirme başarısız, atlandı"; return; }
  calistir "$1" "$KOK/models_bench/$3"
}

[ "${1:-}" = "baslat" ] || { echo "Kullanım: ./bench/run_all.sh baslat"; exit 2; }
TABAN="${DETENTION_MODEL_PATH:-$HOME/case2/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf}"
log "=== benchmark başladı ==="
calistir       "1_qwen3.5-4b-q4_k_m" "$TABAN"
indir_calistir "2_qwen3.5-4b-q6_k"     unsloth/Qwen3.5-4B-GGUF              Qwen3.5-4B-Q6_K.gguf              fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66 3525956768
indir_calistir "3_qwen3.5-2b-q4_k_m"   unsloth/Qwen3.5-2B-GGUF              Qwen3.5-2B-Q4_K_M.gguf            aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223 1280835840
indir_calistir "4_gemma-4-e4b-q4_k_m"  bartowski/google_gemma-4-E4B-it-GGUF google_gemma-4-E4B-it-Q4_K_M.gguf d35a3aa7a6d47de237fd488bb6f7f3efd62908d828f85a63da0ee93acdbefe9f 5405170144
indir_calistir "5_gemma-4-e2b-q4_k_m"  bartowski/google_gemma-4-E2B-it-GGUF google_gemma-4-E2B-it-Q4_K_M.gguf 923c4c86177d2ee173a7f5b4fa3d0ac65f5962ab15e6d6a5bc250aec4fd7bf7e 3462680032
calistir       "6_qwen3.5-4b-q4_k_m_tekrar" "$TABAN"
uv run python bench/summarize.py >> "$LOG" 2>&1
log "=== benchmark bitti ==="
