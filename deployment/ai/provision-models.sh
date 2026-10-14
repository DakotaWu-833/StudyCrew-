#!/bin/sh
set -eu

# This helper creates one temporary local server and stops only its own PID.
: "${STUDYCREW_CHAT_MODEL:=qwen3.5:9b-q4_K_M}"
: "${STUDYCREW_EMBEDDING_MODEL:=qwen3-embedding:0.6b}"
export OLLAMA_HOST=127.0.0.1:11434
/bin/ollama serve &
model_server_pid=$!
cleanup() {
    kill "$model_server_pid" 2>/dev/null || true
    wait "$model_server_pid" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
model_attempt=0
until /bin/ollama list >/dev/null 2>&1; do
    kill -0 "$model_server_pid" 2>/dev/null || { echo 'The temporary model server exited.' >&2; exit 1; }
    model_attempt=$((model_attempt + 1))
    [ "$model_attempt" -lt 60 ] || { echo 'The temporary model server was not ready.' >&2; exit 1; }
    sleep 1
done
/bin/ollama pull "$STUDYCREW_CHAT_MODEL"
/bin/ollama pull "$STUDYCREW_EMBEDDING_MODEL"
/bin/ollama list
