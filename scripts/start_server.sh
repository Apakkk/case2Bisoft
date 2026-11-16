#!/usr/bin/env bash
# llama-server'ı lokal olarak başlatır (yalnızca 127.0.0.1; dışarıya açık değil).
#   -ngl 99 : tüm katmanlar Metal GPU'da     -c 8192 : bağlam (prompt ~1,2k token)
#   -np 1   : tek slot -> temperature 0'da tekrarlanabilir sonuç
#   thinking kapalı: bu sürümde --reasoning varsa "off", yoksa --reasoning-budget 0
set -euo pipefail
KOK="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${LLAMA_SERVER:-$KOK/vendor/llama-b12014/llama-b12014/llama-server}"
if [ ! -x "$SERVER" ] && command -v llama-server >/dev/null; then SERVER="$(command -v llama-server)"; fi
# Kullanım: ./scripts/start_server.sh [model.gguf] [port]
MODEL="${1:-${DETENTION_MODEL_PATH:-$HOME/case2/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf}}"
PORT="${2:-${PORT:-8080}}"
ALIAS="$(basename "$MODEL" .gguf | tr '[:upper:]' '[:lower:]')"
[ -f "$MODEL" ] || { echo "Model bulunamadı: $MODEL (DETENTION_MODEL_PATH ile verin)"; exit 1; }
if "$SERVER" --help 2>&1 | grep -qE -- '--reasoning( |,|$)'; then THINK=(--reasoning off); else THINK=(--reasoning-budget 0); fi
echo "server: $SERVER"; echo "model : $MODEL"; echo "thinking: ${THINK[*]}"
exec "$SERVER" -m "$MODEL" -c 8192 -ngl 99 -np 1 --jinja "${THINK[@]}" \
     --host 127.0.0.1 --port "$PORT" --alias "$ALIAS"
