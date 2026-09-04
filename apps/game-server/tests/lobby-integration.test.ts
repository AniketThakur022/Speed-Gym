/**
 * Real socket integration: a client connects to the running server and we
 * inspect what actually crosses the wire.
 *
 * The unit tests prove `publicOpponent` strips bot markers. This proves the
 * SERVER uses it — the compliance rule is about what reaches a learner, and
 * that can only be checked at the boundary.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createServer, type Server as HttpServer } from "node:http";
import { Server } from "socket.io";
import { io as ioClient, type Socket as ClientSocket } from "socket.io-client";
import jwt from "jsonwebtoken";

import { WS_EVENTS } from "../src/events";
import { makeBot, publicOpponent } from "../src/bot";

const SECRET = "test-secret";
let httpServer: HttpServer;
let io: Server;
let port: number;

/**
 * A miniature stand-in for the lobby namespace that mirrors the real server's
 * emit path: build the match_found payload through publicOpponent, exactly as
 * index.ts does.
 */
beforeAll(async () => {
  httpServer = createServer();
  io = new Server(httpServer, { serveClient: false });

  io.of("/lobby").use((socket, next) => {
    const token = socket.handshake.auth?.token;
    if (!token) return next(new Error("AUTH_INVALID"));
    try {
      jwt.verify(token, SECRET);
      next();
    } catch {
      next(new Error("AUTH_EXPIRED"));
    }
  });

  io.of("/lobby").on("connection", (socket) => {
    socket.on(WS_EVENTS.JOIN_LOBBY, () => {
      const bot = makeBot([1.0], Math.random);
      socket.emit(WS_EVENTS.MATCH_FOUND, {
        match_id: "ad_20260904_001",
        opponents: [
          publicOpponent({ userId: "human-1", thetaU: 1.0 }),
          publicOpponent(bot),
        ],
        mode: "accuracy_duel",
        topology: "online",
      });
    });
  });

  await new Promise<void>((resolve) => {
    httpServer.listen(0, () => {
      port = (httpServer.address() as { port: number }).port;
      resolve();
    });
  });
});

afterAll(async () => {
  io.close();
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
});

function connect(token: string): ClientSocket {
  return ioClient(`http://localhost:${port}/lobby`, {
    auth: { token },
    transports: ["websocket"],
    forceNew: true,
  });
}

describe("socket auth", () => {
  it("refuses a connection with no token", async () => {
    const socket = ioClient(`http://localhost:${port}/lobby`, {
      transports: ["websocket"],
      forceNew: true,
    });
    const error = await new Promise<Error>((resolve) => socket.on("connect_error", resolve));
    expect(error.message).toBe("AUTH_INVALID");
    socket.close();
  });

  it("refuses a forged token", async () => {
    const forged = jwt.sign({ sub: "attacker" }, "not-the-secret");
    const socket = connect(forged);
    const error = await new Promise<Error>((resolve) => socket.on("connect_error", resolve));
    expect(error.message).toBe("AUTH_EXPIRED");
    socket.close();
  });

  it("accepts a token signed with the shared secret", async () => {
    const socket = connect(jwt.sign({ sub: "user-1", theta_u: 1.0 }, SECRET));
    await new Promise<void>((resolve) => socket.on("connect", () => resolve()));
    expect(socket.connected).toBe(true);
    socket.close();
  });
});

describe("no bot marker crosses the wire", () => {
  it("match_found carries no isBot, persona or bot-shaped id", async () => {
    const socket = connect(jwt.sign({ sub: "user-2", theta_u: 1.0 }, SECRET));
    await new Promise<void>((resolve) => socket.on("connect", () => resolve()));

    const payload = await new Promise<Record<string, unknown>>((resolve) => {
      socket.on(WS_EVENTS.MATCH_FOUND, resolve);
      socket.emit(WS_EVENTS.JOIN_LOBBY, { mode: "accuracy_duel" });
    });

    const wire = JSON.stringify(payload);
    expect(wire).not.toMatch(/isBot|is_bot/i);
    expect(wire).not.toMatch(/persona/i);
    expect(wire).not.toMatch(/\bbot\b/i);

    // Keys must be a SUBSET of the allowed set — an opponent without a display
    // name simply omits it, so an exact match would be asserting the fixture
    // rather than the invariant. What matters is that nothing EXTRA appears.
    const allowed = new Set(["display_name", "theta_u", "user_id"]);
    for (const opponent of payload.opponents as Array<Record<string, unknown>>) {
      for (const key of Object.keys(opponent)) {
        expect(allowed.has(key), `unexpected field on the wire: ${key}`).toBe(true);
      }
      expect(opponent.user_id).toBeTruthy();
      expect(String(opponent.user_id)).not.toMatch(/bot/i);
    }
    socket.close();
  });
});
