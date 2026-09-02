/**
 * Socket.IO event contract — RFP §24 names VERBATIM (GATE-06 tests these 9).
 * The v5.2 corpus had two divergent vocabularies; this is the canonical one.
 */
export const WS_EVENTS = {
  JOIN_LOBBY: "join_lobby",
  MATCH_FOUND: "match_found",
  ROUND_STARTED: "round_started",
  SUBMIT_GAME_ANSWER: "submit_game_answer",
  ROUND_ENDED: "round_ended",
  MATCH_ENDED: "match_ended",
  BOSS_BATTLE_DAMAGE: "boss_battle_damage",
  RELAY_BATON_PASS: "relay_baton_pass",
  TEAM_MORALE_UPDATE: "team_morale_update",
} as const;

export type WsEvent = (typeof WS_EVENTS)[keyof typeof WS_EVENTS];
