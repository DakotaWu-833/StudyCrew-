# Compatible chat with local embeddings

The optional settings in `studycrew-compatible-local-embeddings.env.example`
split chat generation and Agent tool calls from vector inference. Chat uses an
approved HTTPS compatible API; embedding requests use the independently selected
Ollama endpoint. This avoids loading the chat model on a small web host. Actual
memory, latency, provider quotas and five-user operation still require testing.

Keep Ollama bound to `127.0.0.1:11434`, running only the selected embedding model.
Do not expose its port through the security group or host firewall. Warm an
embedding request and record the installed model's digest from `/api/tags` in
`RAG_EMBEDDING_REVISION`; changing model weights requires updating that value.
Use bounded batches suitable for the measured host capacity.

The small Learner Lab profile uses `all-minilm:l6-v2` with 384 dimensions. This
lightweight model targets English sentence retrieval. Its 256-token context can
reject long or CJK inputs, which visibly fall back to keyword search. Select and
measure a larger multilingual model before claiming multilingual semantic
coverage; changing dimensions also changes the vector-cache namespace.

Merge the example into the existing protected application environment. Store the
chat API key there, never in source, command arguments, browser code or logs.
For a local unauthenticated Ollama service, explicitly leave
`RAG_EMBEDDING_API_KEY` empty. A separate remote embedding gateway needs its own
bearer key and trusted HTTPS. Provider URLs cannot contain embedded credentials,
query strings or fragments; non-loopback HTTP and malformed credentials fail
before a network request.

With the new embedding provider/base settings unset, the original shared Ollama
configuration and credential remain supported. Once either setting selects a
separate transport, the chat credential is never inherited. Set an embedding key
explicitly if that transport needs authentication. Embedding response limits,
finite vector validation, total deadlines and keyword fallback are unchanged.

Only the authorized excerpts needed for a question/tool request go to the
configured chat provider. Select a provider under the team's privacy rules and
verify its current quotas. No model accuracy, SMTP, TLS, capacity or external API
result is established by these configuration examples or unit tests.
