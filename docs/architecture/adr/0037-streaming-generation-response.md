# ADR-0037: Streaming generation response shape (SSE)

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** api, ux, streaming, sse

## Context

`POST /query` today returns the full `QueryResponse` only after the
LLM finishes generating. With Ollama Llama 3.1 8B on the demo
hardware that's 3–8s of perceived blank screen. The frontend
playground already streams the *trace* via SSE (`GET
/query/{id}/trace/stream`), so the user sees retrieval candidates as
they land — but the *answer text* arrives in one chunk.

Production RAG UX expects token-by-token streaming for the answer.
LiteLLM, OpenAI, Anthropic, and Ollama all support streaming. The
question is what wire format we use to surface it.

Constraints:

- The existing trace stream is SSE — easier to follow the precedent
  than introduce a second pattern.
- The orchestrator persists the full response (with grounding /
  citations / cost) at the end of the call. The streamed tokens are
  presentation-layer only; the audit + cost story doesn't change.
- The cascade in [ADR-0010](0010-layered-hallucination-detection.md)
  needs the *full* answer text to score grounding + NLI. We can't
  emit a final grounding verdict until generation finishes — that
  needs to be the last frame.
- Idempotency (R3.S2) is response-cached, not token-cached — a
  replay of a streamed query returns the full response, not a fresh
  stream.
- The `/query` API contract is widely consumed; we can't break it.

## Decision

Add a **new endpoint** `POST /query/stream` that returns
**Server-Sent Events** (`text/event-stream`). The non-streaming
`POST /query` stays exactly as it is — clients that want the
streamed UX opt in by hitting the new path.

### Frame shape

```
event: token
data: {"text":"The "}

event: token
data: {"text":"deployment "}

...

event: citation
data: {"index":1,"chunk_id":"...","document_id":"...","quoted_text":"..."}

event: grounding
data: {"grounding_score":0.83,"nli_verdict":"entail","judge_verdict":null}

event: usage
data: {"input_tokens":412,"output_tokens":127,"cost_usd":0.0012,"latency_ms":3814}

event: done
data: {"query_session_id":"..."}
```

- `event: token` frames are emitted as the LLM yields. The data
  payload is `{"text": "<chunk>"}` — no escaping besides JSON
  string escaping.
- `event: citation` frames are emitted **after** the LLM finishes
  (citations are derived from the persisted answer + the existing
  `referenced_indices` helper). Doing them per-token would be
  premature — the model may emit `[1]` mid-thought and later
  contradict it.
- `event: grounding` carries the cascade verdicts. One frame at
  end-of-generation.
- `event: usage` carries the cost + latency, mirroring the
  non-streaming response's `usage` block.
- `event: done` is the terminal frame and carries the
  `query_session_id` so the client can deep-link to the trace UI.
- A keep-alive comment (`: keepalive\n\n`) is emitted every 15s if
  the LLM is slow, so proxies don't drop the connection.

### Order of operations on the server side

1. Run retrieval, rerank, context-assembly, prompt resolution,
   budget gate, exactly as `POST /query` does today.
2. Call `LiteLLMGenerator.stream(...)` (new method to add — uses
   `litellm.acompletion(stream=True)`). Iterate over chunks; for
   each, emit `event: token`.
3. After the stream completes, run grounding + persistence + audit
   as the non-streaming path does today.
4. Emit `event: citation` × N, then `event: grounding`, then
   `event: usage`, then `event: done`.
5. If anything inside steps 1–3 raises, emit a single
   `event: error` frame and close: `data: {"reason":"...","detail":"..."}`.

### Errors

`event: error` carries the same `reason` taxonomy as the non-
streaming failure-audit metadata (R3.S4):

| reason | When |
|---|---|
| `provider_timeout` | LiteLLM call exceeded `generation_timeout_seconds` |
| `internal_error` | Any other unhandled exception during the streamed flow |
| `budget_denied` | Budget gate raised before generation; emitted as the only frame in the stream |
| `abstained` | The orchestrator's `abstain_if_unsupported` short-circuit fired; the response body is the canned abstention answer and grounding/usage are still emitted |

### Why SSE, not WebSockets

- SSE is one-way (server → client) which matches the use case
  exactly. WebSockets adds a control plane we don't use.
- Browsers, proxies, and load balancers handle SSE as a long-lived
  GET/POST; no protocol-upgrade hop.
- The existing `/query/{id}/trace/stream` endpoint already
  established the SSE pattern; the frontend already handles it.
- Backpressure: SSE has no built-in backpressure protocol, but
  `litellm.acompletion(stream=True)` is an async generator — we
  `await` between yields, so a slow client naturally back-pressures
  the source iterator by not draining. The connection's TCP window
  shoulders the rest.

### Why not response-streamed JSON (`Transfer-Encoding: chunked`)

- Multiple event types are easier to parse client-side as SSE
  frames vs. a JSON stream that the client has to delimit.
- The Anthropic & OpenAI assistants APIs both ship SSE; matching the
  industry pattern lowers the integration cost for future SDK
  consumers.

### Why a new endpoint, not a `?stream=true` flag on `POST /query`

- The response media type is different (`application/json` vs
  `text/event-stream`). Mixing them under one path means the OpenAPI
  schema can't accurately describe either case.
- Idempotency-key handling (R3.S2) is different for streamed
  responses — we can't replay tokens deterministically. Splitting
  the endpoint makes the contract honest.
- Clients that don't want streaming don't accidentally trip into a
  different response shape by toggling a flag.

### Auth / RBAC / RLS

Identical to `POST /query` — `queries:execute` permission required,
same Idempotency-Key support (an idempotent replay just returns the
cached `QueryResponse` as a one-shot `data:` frame followed by
`event: done`), same budget gate, same NetworkPolicy.

### Frontend integration

The Next.js query-playground page already wires `useTraceStream` for
the trace. A parallel `useAnswerStream` hook follows the same
EventSource pattern; the answer streams into the answer card while
the trace card fills in. Buffering rule: paint the answer at the end
of each `event: token` frame, debounced to at most 30fps so React
doesn't thrash.

## Consequences

### Positive

- Perceived latency drops from 3–8s to ~300ms first-token. That's
  the gap between "OK the system noticed I asked something" and
  "OK it's still alive." Big UX win.
- The pattern matches OpenAI / Anthropic so an SDK consumer porting
  from there has no learning curve.
- The non-streaming `/query` stays untouched. Existing clients
  (Temporal evaluation worker, internal tooling) keep their
  behavior.
- The cascade / persistence / audit stages run in the same order
  as today — no semantic divergence between streamed and non-
  streamed flows.

### Negative

- Two endpoints to keep in sync. A bug fix in one must land in the
  other. Mitigated by sharing the orchestrator (the streaming
  endpoint is a thin wrapper that intercepts the generation stage's
  output).
- SSE is finicky behind some load balancers (some buffer responses
  before flushing). The existing `/query/{id}/trace/stream`
  endpoint already deals with this — same headers
  (`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`).
- Idempotent replay can't replay tokens; it emits the cached
  response as one frame. Document this in the API reference.

### Neutral

- Adds a new permission-less surface on the same route prefix; no
  RBAC migration needed.
- The OpenAPI spec gains a `text/event-stream` response media type
  on the new path. FastAPI handles this with `responses={200: {"content": {"text/event-stream": {}}}}`.

## Alternatives considered

### Option A — SSE on a new endpoint (this)
- See above.

### Option B — WebSocket bidirectional
- **Pros:** Future-proof for client-initiated cancellation
  (`/query/cancel`).
- **Cons:** Two-way protocol for a one-way flow. Browser EventSource
  is simpler; WebSocket adds backend complexity (frame parsing,
  ping/pong).
- **Rejected because:** SSE solves the same problem with less
  surface area. Revisit when client-initiated cancellation becomes a
  real requirement.

### Option C — Response-streamed JSON over HTTP/1.1 chunked
- **Pros:** Single endpoint; native to `httpx.stream()`.
- **Cons:** Client has to delimit messages itself; multiple event
  types are awkward; no industry precedent.
- **Rejected because:** SSE is the de-facto standard for LLM
  streaming.

### Option D — gRPC streaming
- **Pros:** Multi-language client SDKs; backpressure built in.
- **Cons:** Browsers don't speak gRPC directly; would need
  gRPC-Web which adds a proxy hop.
- **Rejected because:** [ADR-0009](0009-rest-not-grpc.md) locked
  REST as the inter-service contract; the frontend is a browser
  client.

## Trade-off summary

| Dimension | SSE (this) | WebSocket | Chunked JSON | gRPC |
|---|---|---|---|---|
| Browser support | Native (EventSource) | Native (WebSocket) | Native (Fetch stream) | gRPC-Web proxy |
| Backend complexity | Low | Medium | Low | Medium |
| Industry pattern | Standard for LLM streaming | Less common | Niche | Not browser-friendly |
| Multiple frame types | Native (event:) | Application-defined | Application-defined | Native (oneof) |
| Reverse-proxy fragility | Medium | Medium | Low | Low |
| Implementation effort | Bounded | Higher | Bounded | High |

## Notes on the design docs

PRD § 4 lists "streamed responses" as a v1 expectation. This ADR
commits to SSE + a new endpoint. The implementation phase adds:

- `LiteLLMGenerator.stream(...)` async-iterator method.
- `POST /query/stream` route in `apps/api/app/api/v1/routes/query.py`.
- `useAnswerStream` hook in `apps/frontend/src/lib/`.
- OpenAPI doc update under `apps/api/app/schemas/query.py`.

`Enterprise_RAG_Architecture.md` § "API" should reference this ADR
when the implementation lands.

## References

- [ADR-0009](0009-rest-not-grpc.md) — REST contract between
  components (rules out gRPC for the browser client)
- [ADR-0010](0010-layered-hallucination-detection.md) — grounding
  cascade; runs after the stream completes
- [ADR-0014](0014-hybrid-llm-strategy.md) — LiteLLM gateway; the
  underlying streaming API
- The existing `/query/{id}/trace/stream` SSE route in
  `apps/api/app/api/v1/routes/query.py` — same pattern as this new
  endpoint
- [MDN — Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [WHATWG HTML — EventSource](https://html.spec.whatwg.org/multipage/server-sent-events.html)
