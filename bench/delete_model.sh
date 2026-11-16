#!/usr/bin/env bash
# Benchmark modelini siler. Kullanım: ./bench/delete_model.sh <dosya.gguf>
# Yalnızca proje içindeki models_bench/ klasöründeki .gguf (ve yarım .part) dosyasını siler:
# önce o klasöre girer (yoksa durur), dosya adı da eğik çizgi içeremez; proje dışına çıkamaz.
set -euo pipefail
DOSYA="$1"
[[ "$DOSYA" =~ ^[A-Za-z0-9._-]+\.gguf$ ]] || { echo "geçersiz dosya adı"; exit 2; }
cd "$(dirname "$0")/../models_bench"
rm -f "./$DOSYA" "./$DOSYA.part"
echo "silindi: models_bench/$DOSYA"; df -h . | awk 'NR==2{print "boş:", $4}'
