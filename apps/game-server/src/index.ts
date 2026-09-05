/**
 * VMSG game server — Socket.IO v4 on :3001, internal behind Traefik `/game`.
 *
 * Authoritative for match state, timing and scoring. It shares JWT_SECRET with
 * FastAPI as deploy-time config (no runtime auth call) and persists results
 * through the loopback internal API — it never writes Postgres itself.
 *
 * Event names are the RFP §24 set verbatim (see events.ts). The rules live in
 * duel.ts / matchmaking.ts so they can be tested without a socket.
 */
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { Server, type Socket } from "socket.io";
import jwt from "jsonwebtoken";

import { WS_EVENTS } from "./events.js";
import {
  findMatch,
  seedElo,
  type Cluster,
  type MatchmakingProfile,
} from "./matchmaking.js";
import {
  botsAllowedFor,
  makeBot,
  publicOpponent,
  weightBotEloChange,
  type BotProfile,
} from "./bot.js";
import {
  COUNTDOWN_SECONDS,
  DISCONNECT_GRACE_MS,
  beginRound,
  checkDisconnectForfeit,
  createMatch,
  expireTurn,
  makeMatchId,
  markDisconnected,
  markReconnected,
  newHeartbeatLedger,
  opponentOf,
  playerOf,
  recordHeartbeat,
  resolveAnswer,
  scoreDuel,
  staleHeartbeats,
  HEARTBEAT_TIMEOUT_MS,
  type DuelMatch,
} from "./duel.js";

const PORT = Number(process.env.PORT ?? 3001);
const JWT_SECRET = process.env.JWT_SECRET ?? "dev-only-change-me";
const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? "http://localhost:8000";
const INTERNAL_KEY = process.env.INTERNAL_API_KEY ?? "dev-internal-key";

interface AuthedSocket extends Socket {
  data: { userId?: string; thetaU?: number; matchId?: string };
}

/** In-process state. Phase 2 moves this to Redis with the Socket.IO adapter;
 *  the shapes here mirror the documented `match:{id}:state` fields. */
const queue = new Map<string, MatchmakingProfile>();
const matches = new Map<string, DuelMatch>();
const answers = new Map<string, string>(); // matchId → expected answer, SERVER ONLY
const turnTimers = new Map<string, NodeJS.Timeout>();
/** matchId → the bot in that match, if any. INTERNAL ONLY: this map is the
 *  single place the server knows an opponent is synthetic, and nothing derived
 *  from it may be emitted to a client. */
const matchBots = new Map<string, BotProfile>();
const playerAges = new Map<string, number | null>();
const heartbeats = newHeartbeatLedger();
let matchSequence = 0;

const httpServer = createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(
      JSON.stringify({
        status: "ok",
        service: "vmsg-game-server",
        queued: queue.size,
        activeMatches: matches.size,
      }),
    );
    return;
  }
  res.writeHead(404);
  res.end();
});

const io = new Server(httpServer, { serveClient: false, cors: { origin: false } });

function authMiddleware(socket: AuthedSocket, next: (err?: Error) => void) {
  const token = socket.handshake.auth?.token;
  if (!token) return next(new Error("AUTH_INVALID"));
  try {
    const payload = jwt.verify(token, JWT_SECRET) as { sub?: string; theta_u?: number };
    socket.data.userId = payload.sub;
    socket.data.thetaU = payload.theta_u ?? 0;
    next();
  } catch {
    next(new Error("AUTH_EXPIRED"));
  }
}

for (const namespace of ["/lobby", "/game", "/spectate"]) {
  io.of(namespace).use(authMiddleware as never);
}

async function internalPost(path: string, body: unknown): Promise<unknown> {
  const response = await fetch(`${INTERNAL_API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Key": INTERNAL_KEY },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`internal API ${path} → ${response.status}`);
  return response.json();
}

// ── Lobby ───────────────────────────────────────────────────────────────────

io.of("/lobby").on("connection", (socket: AuthedSocket) => {
  socket.on(WS_EVENTS.JOIN_LOBBY, async (payload: { mode?: string; topology?: string }, ack?: Function) => {
    const userId = socket.data.userId!;
    const profile: MatchmakingProfile = {
      userId,
      thetaU: socket.data.thetaU ?? 0,
      elo: seedElo(socket.data.thetaU ?? 0),
      cluster: "balanced" as Cluster,
      latencyMs: 50,
      queueJoinTimeMs: Date.now(),
    };

    // Age comes from the account, not the client: the COPPA gate must not be
    // something a caller can talk its way past by omitting a field.
    let age: number | null = playerAges.get(userId) ?? null;
    if (!playerAges.has(userId)) {
      try {
        const context = (await internalPost("/internal/user/context", { user_id: userId })) as {
          age_group?: number;
        };
        age = typeof context.age_group === "number" ? context.age_group : null;
      } catch {
        age = null; // unknown age -> bots are refused downstream, which is the safe default
      }
      playerAges.set(userId, age);
    }

    const decision = findMatch(profile, [...queue.values()], Date.now());
    if (decision.type === "matched" && decision.opponent) {
      queue.delete(decision.opponent.userId);
      await startMatch(profile, decision.opponent);
      ack?.({ status: "matched" });
      return;
    }

    if (decision.type === "bot_fill") {
      const eligibility = botsAllowedFor({ age, mode: payload?.mode ?? "accuracy_duel" });
      if (eligibility.allowed) {
        const waiting = [...queue.values()].map((p) => p.thetaU);
        const bot = makeBot(waiting.length ? waiting : [profile.thetaU], Math.random);
        queue.delete(userId);
        await startMatch(profile, bot, bot);
        ack?.({ status: "matched" });
        return;
      }
      // Not eligible for a bot: keep waiting for a human rather than telling the
      // client why, which would disclose that bots exist for other players.
      queue.set(userId, profile);
      ack?.({ status: "waiting" });
      return;
    }

    queue.set(userId, profile);
    ack?.({ status: decision.type, estimated_wait_seconds: decision.estimatedWaitSeconds });
  });

  socket.on("disconnect", () => {
    if (socket.data.userId) queue.delete(socket.data.userId);
  });
});

async function startMatch(
  a: MatchmakingProfile,
  b: MatchmakingProfile | BotProfile,
  bot?: BotProfile,
): Promise<void> {
  const matchId = makeMatchId(new Date(), ++matchSequence);
  if (bot) matchBots.set(matchId, bot);
  const match = createMatch(
    matchId,
    { userId: a.userId, thetaU: a.thetaU, age: 20 },
    { userId: b.userId, thetaU: b.thetaU, age: 20 },
    Date.now(),
  );
  matches.set(matchId, match);

  io.of("/lobby").emit(WS_EVENTS.MATCH_FOUND, {
    match_id: matchId,
    // publicOpponent strips isBot/persona: a serialization slip here would
    // disclose a synthetic opponent to the client.
    opponents: [publicOpponent(a), publicOpponent(b)],
    mode: "accuracy_duel",
    topology: "online",
  });

  // 5-second countdown, one tick per second, then the first round.
  for (let remaining = COUNTDOWN_SECONDS; remaining > 0; remaining--) {
    io.of("/lobby").to(matchId).emit("lobby:countdown", { seconds_remaining: remaining });
  }
  setTimeout(() => emitRound(matchId), COUNTDOWN_SECONDS * 1000);
}

// ── Game ────────────────────────────────────────────────────────────────────

async function emitRound(matchId: string): Promise<void> {
  const match = matches.get(matchId);
  if (!match || match.phase === "completed") return;

  const round = beginRound(match, Date.now());

  let problem: { problem_id: string; problem_text: string; answer: string; difficulty: number };
  try {
    const batch = (await internalPost("/internal/game/problem-batch", {
      count: 1,
      difficulty_range: [round.difficulty, round.difficulty + 1],
    })) as { problems: (typeof problem)[] };
    problem = batch.problems[0];
  } catch {
    io.of("/game").to(matchId).emit("error", { code: "INTERNAL_ERROR", message: "no problem available" });
    return;
  }

  // The answer stays server-side. The round payload deliberately omits it —
  // an online client must never be able to read the answer it is being asked.
  answers.set(matchId, problem.answer);

  io.of("/game").to(matchId).emit(WS_EVENTS.ROUND_STARTED, {
    match_id: matchId,
    round_number: round.round_number,
    active_user_id: round.activeUserId,
    problem: {
      problem_id: problem.problem_id,
      problem_text: problem.problem_text,
      difficulty: round.difficulty,
      time_limit_ms: round.time_limit_ms,
    },
  });

  clearTimeout(turnTimers.get(matchId));
  turnTimers.set(
    matchId,
    setTimeout(() => {
      const current = matches.get(matchId);
      if (!current || current.phase === "completed") return;
      void finishMatch(matchId, expireTurn(current));
    }, round.time_limit_ms),
  );
}

io.of("/game").on("connection", (socket: AuthedSocket) => {
  socket.on("game:join", ({ match_id }: { match_id: string }) => {
    socket.join(match_id);
    socket.data.matchId = match_id;
    recordHeartbeat(heartbeats, socket.data.userId!, Date.now());
    const match = matches.get(match_id);
    if (match) markReconnected(match, socket.data.userId!);
  });

  socket.on("game:heartbeat", () => {
    recordHeartbeat(heartbeats, socket.data.userId!, Date.now());
    const match = socket.data.matchId ? matches.get(socket.data.matchId) : undefined;
    // A heartbeat from a player we had marked gone is a reconnect.
    if (match && !playerOf(match, socket.data.userId!)?.connected) {
      markReconnected(match, socket.data.userId!);
    }
  });

  socket.on(
    WS_EVENTS.SUBMIT_GAME_ANSWER,
    (
      payload: {
        match_id: string;
        problem_id: string;
        answer: string;
        client_timestamp_ms: number;
        keystroke_intervals_ms?: number[];
      },
      ack?: Function,
    ) => {
      const match = matches.get(payload.match_id);
      if (!match) return ack?.({ code: "MATCH_NOT_FOUND" });
      recordHeartbeat(heartbeats, socket.data.userId!, Date.now());

      const expected = answers.get(payload.match_id) ?? "";
      let resolution;
      try {
        resolution = resolveAnswer(
          match,
          socket.data.userId!,
          payload.answer,
          expected,
          payload.client_timestamp_ms || Date.now(),
          payload.keystroke_intervals_ms,
        );
      } catch (error) {
        // NOT_YOUR_TURN, SUB_200MS, MISSING_KEYSTROKES: the round stays open
        // and the turn timer keeps running — a refused paste costs time, it
        // does not grant a retry.
        return ack?.({ code: (error as Error).message });
      }

      clearTimeout(turnTimers.get(payload.match_id));

      io.of("/game").to(payload.match_id).emit(WS_EVENTS.ROUND_ENDED, {
        problem_id: payload.problem_id,
        user_id: socket.data.userId,
        correct: resolution.correct,
        points_earned: resolution.correct ? 2 : -1,
        // The answer is only ever revealed once the round is over.
        correct_answer: resolution.correct ? undefined : expected,
      });
      ack?.({ correct: resolution.correct });

      if (resolution.matchOver) {
        void finishMatch(payload.match_id, resolution);
      } else {
        void emitRound(payload.match_id);
      }
    },
  );

  socket.on("disconnect", () => {
    const matchId = socket.data.matchId;
    const match = matchId ? matches.get(matchId) : undefined;
    if (!match || !socket.data.userId) return;

    markDisconnected(match, socket.data.userId, Date.now());
    io.of("/game").to(match.matchId).emit("game:player_disconnected", {
      user_id: socket.data.userId,
      grace_period_seconds: DISCONNECT_GRACE_MS / 1000,
    });

    setTimeout(() => {
      const current = matches.get(match.matchId);
      if (!current || current.phase === "completed") return;
      const forfeit = checkDisconnectForfeit(current, Date.now());
      if (forfeit) void finishMatch(current.matchId, forfeit);
    }, DISCONNECT_GRACE_MS);
  });
});

async function finishMatch(
  matchId: string,
  resolution: { winnerUserId?: string; eliminationReason?: string },
): Promise<void> {
  const match = matches.get(matchId);
  if (!match) return;

  const bot = matchBots.get(matchId);

  clearTimeout(turnTimers.get(matchId));
  turnTimers.delete(matchId);

  const outcomes = scoreDuel(
    [match.players[0].tally, match.players[1].tally],
    resolution.winnerUserId ?? match.players[0].userId,
  );

  // Persist BEFORE announcing: the payload carries elo_change, which only the
  // persist call can produce. (BACKEND_ARCHITECTURE §8.1 emits first, but its
  // own payload then has no ELO to report; API_SPEC's flow has this order.)
  let eloUpdates: unknown = [];
  try {
    const persisted = (await internalPost("/internal/match/complete", {
      match_id: matchId,
      mode: "accuracy_duel",
      topology: "online",
      results: outcomes.map((o) => ({
        user_id: o.userId,
        // is_bot is persisted server-side for auditing but is stripped from
        // every client-facing payload (see publicOpponent).
        is_bot: bot?.userId === o.userId,
        final_rank: o.rank,
        final_score: o.finalScore,
        problems_attempted: o.problemsAttempted,
        problems_correct: o.problemsCorrect,
        accuracy_pct: o.accuracyPct,
        avg_time_ms: o.avgTimeMs,
        position_points: o.positionPoints,
        accuracy_bonus: o.accuracyBonus,
      })),
    })) as { elo_updates?: unknown };
    eloUpdates = persisted.elo_updates ?? [];
  } catch (error) {
    // A persistence failure must not strand players in a finished match.
    console.error(`match ${matchId}: persist failed`, error);
  }

  io.of("/game").to(matchId).emit(WS_EVENTS.MATCH_ENDED, {
    match_id: matchId,
    rankings: outcomes.map((o) => ({
      user_id: o.userId,
      rank: o.rank,
      score: o.finalScore,
      accuracy: o.accuracyPct,
      avg_time: o.avgTimeMs,
    })),
    elimination_reason: resolution.eliminationReason,
    // A result against a bot moves the rating half as far: a bot is a
    // calibrated approximation of an opponent, not an opponent.
    elo_updates: bot
      ? (eloUpdates as Array<{ user_id: string; elo_change: number }>).map((u) => ({
          ...u,
          elo_change: weightBotEloChange(u.elo_change ?? 0),
          bot_round: true,
        }))
      : eloUpdates,
  });

  matches.delete(matchId);
  answers.delete(matchId);
  matchBots.delete(matchId);
}

// Heartbeat sweep. A half-open socket never emits "disconnect", so silence is
// the only signal for a phone that fell off WiFi; treating it as a disconnect
// starts the same 15s grace clock the socket-close path uses.
setInterval(() => {
  const now = Date.now();
  for (const userId of staleHeartbeats(heartbeats, now)) {
    for (const match of matches.values()) {
      const player = playerOf(match, userId);
      if (player && player.connected && match.phase !== "completed") {
        markDisconnected(match, userId, now);
        io.of("/game").to(match.matchId).emit("game:player_disconnected", {
          user_id: userId,
          grace_period_seconds: DISCONNECT_GRACE_MS / 1000,
        });
        setTimeout(() => {
          const current = matches.get(match.matchId);
          if (!current || current.phase === "completed") return;
          const forfeit = checkDisconnectForfeit(current, Date.now());
          if (forfeit) void finishMatch(current.matchId, forfeit);
        }, DISCONNECT_GRACE_MS);
      }
    }
    heartbeats.lastSeenMs.delete(userId); // handled; a new heartbeat re-registers
  }
}, HEARTBEAT_TIMEOUT_MS / 2).unref();

httpServer.listen(PORT, () => {
  console.log(`vmsg-game-server listening on :${PORT}`);
  console.log(`events: ${Object.values(WS_EVENTS).join(", ")}`);
});

export { io, httpServer };
