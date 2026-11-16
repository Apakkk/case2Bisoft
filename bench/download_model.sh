#!/usr/bin/env bash
# Benchmark modeli indirir. Kullanım: ./bench/download_model.sh <repo> <dosya.gguf> <sha256> <boyut_bayt>
# Güvenlik: yalnızca proje içindeki models_bench/ klasörüne yazar; indirmeden sonra en az 2 GB boş
# kalmıyorsa indirmez; SHA-256 tutmazsa yarım dosyayı siler.
set -euo pipefail
REPO="$1"; DOSYA="$2"; SHA="$3"; BOYUT="$4"
[[ "$REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "geçersiz repo"; exit 2; }
[[ "$DOSYA" =~ ^[A-Za-z0-9._-]+\.gguf$ ]] || { echo "geçersiz dosya adı"; exit 2; }
[[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "geçersiz sha256"; exit 2; }
[[ "$BOYUT" =~ ^[0-9]+$ ]] || { echo "geçersiz boyut"; exit 2; }
mkdir -p "$(dirname "$0")/../models_bench"
cd "$(dirname "$0")/../models_bench"     # bundan sonraki her yol bu klasöre göredir
if [ -f "./$DOSYA" ] && echo "$SHA  ./$DOSYA" | shasum -a 256 -c - >/dev/null 2>&1; then
  echo "zaten var: models_bench/$DOSYA"; exit 0
fi
BOS_KB=$(df -k . | awk 'NR==2{print $4}')
GEREKEN_KB=$(( BOYUT / 1024 + 2 * 1024 * 1024 ))
if (( BOS_KB < GEREKEN_KB )); then
  echo "YETERSİZ DİSK: boş $((BOS_KB/1024)) MB, gereken $((GEREKEN_KB/1024)) MB (dosya + 2 GB pay)"; exit 3
fi
curl -fL --retry 3 -sS -o "./$DOSYA.part" "https://huggingface.co/$REPO/resolve/main/$DOSYA"
if echo "$SHA  ./$DOSYA.part" | shasum -a 256 -c - >/dev/null; then
  mv "./$DOSYA.part" "./$DOSYA"; echo "OK: models_bench/$DOSYA"
else
  rm -f "./$DOSYA.part"; echo "SHA-256 TUTMADI, yarım dosya silindi"; exit 4
fi
