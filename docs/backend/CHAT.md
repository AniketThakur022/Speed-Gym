# Study chatbot (block 7) — hints only, no RAG

Code: `services/api/app/chat/` (hints, llm, budget), router `chat.py`, migration
`145_chat.sql`; tests `test_chat.py`. Flags: `chatbot` (on), `chatbot_llm` (dark).

Settled constraints: the owner's 2026-09-02 decision — **the chatbot does not use
RAG**; the architecture's hard gate — **never gives direct answers, hints/scaffolding
only** (RAG-EXP-01/02); no live LLM in the game loop — the chatbot is opt-in, online,
and outside the practice loop.

## `POST /api/v1/chat/query {template_id, level?, message?, prior_hint?}`

- **Hint ladder** (default, no key needed): built from the problem's own verified
  SolveAlong steps *minus the final step* (which is the answer). Level 1 frames the
  method (technique/sutra/topic); levels 2–3 are the next verified steps. `max_level`
  is bounded by the steps available; a one-step problem yields only the framing hint.
- **Claude path** (only when `chatbot_llm` is on AND the owner key is in `.env` AND
  the learner has budget): the model (`claude-opus-5`, adaptive thinking, low effort,
  server-side refusal fallbacks) receives the problem, the method and the steps
  *without the final one*, under a system prompt whose only rules are the hard gate.
  A refusal or an outage falls back to the ladder (`fallback` says which).
- **Answer-leak filter** on every output, ladder or model: every surface form of the
  answer (`9506`, `9,506`, `9506.0`, …) is replaced by `▮`, word-boundary aware, and
  `leak_redacted` reports when it fired.
- **Budget**: `CHAT_DAILY_TOKEN_BUDGET` (20k) per learner per UTC day, input+output;
  exhausted → 429 for the model path while the ladder keeps working. `chat_usage` and
  `chat_log` are the cost dashboard.

Never in a response: the answer, the final step, retrieved passages.
