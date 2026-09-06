"""Study chatbot (block 7) — hints only, no RAG, no answers.

Two paths behind one route:
* the deterministic hint ladder built from a problem's own solution steps
  (works without any key, cacheable, safe offline);
* an optional Claude path (flag `chatbot_llm` + owner key) that rephrases and
  answers follow-up questions under the same hard gate and a daily token
  budget. Every output passes the answer-leak filter before it leaves.
"""
