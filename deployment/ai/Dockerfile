# GPU inference only; the reviewed Django/Nginx deployment stays separate.
FROM ollama/ollama:0.40.3

ENV OLLAMA_MODELS=/models \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_NO_CLOUD=true \
    OLLAMA_NOHISTORY=true \
    OLLAMA_DEBUG=false \
    OLLAMA_DEBUG_LOG_REQUESTS=false \
    HOME=/tmp

COPY provision-models.sh /provision-models.sh
RUN chmod 0555 /provision-models.sh

ENTRYPOINT ["/bin/ollama"]
CMD ["serve"]
