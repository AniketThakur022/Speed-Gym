/**
 * VMSG game server — Socket.IO v4, port 3001 (internal behind Traefik /game).
 * Shares JWT_SECRET with FastAPI as deploy-time config (no runtime call).
 * Authoritative for match state/timing/scoring; persists via the FastAPI
 * Internal API. Sprint-0 scope: JWT handshake + namespaces + §24 event stubs.
 */
import { createServer } from "node:http";
import { Server, type Socket } from "socket.io";
import jwt from "jsonwebtoken";
import { WS_EVENTS } from "./events.js";

const PORT = Number(process.env.PORT ?? 3001);
const JWT_SECRET = process.env.JWT_SECRET ?? "dev-only-change-me";

const httpServer = createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok", service: "vmsg-game-server" }));
    return;
  }
  res.writeHead(404);
  res.end();
});

const io = new Server(httpServer, {
  serveClient: false,
  cors: { origin: false },
});

interface AuthedSocket extends Socket {
  data: { userId?: string };
}

function authMiddleware(socket: AuthedSocket, next: (err?: Error) => void) {
  const token = socket.handshake.auth?.token;
  if (!token) return next(new Error("missing token"));
  try {
    const payload = jwt.verify(token, JWT_SECRET) as { sub?: string };
    socket.data.userId = payload.sub;
    next();
  } catch {
    next(new Error("invalid token"));
  }
}

for (const ns of ["/lobby", "/game", "/spectate"]) {
  io.of(ns).use(authMiddleware);
}

io.of("/lobby").on("connection", (socket: AuthedSocket) => {
  socket.on(WS_EVENTS.JOIN_LOBBY, (payload, ack) => {
    // Sprint-3 scope: matchmaking via Redis sorted sets. Stub acknowledges.
    ack?.({ status: "queued", userId: socket.data.userId, payload: payload ?? null });
  });
});

io.of("/game").on("connection", (socket: AuthedSocket) => {
  socket.on(WS_EVENTS.SUBMIT_GAME_ANSWER, (payload, ack) => {
    // Server-authoritative validation lands in Sprint 3 (anti-cheat SAFE-GATE-01).
    ack?.({ status: "received", echo: payload ?? null });
  });
});

io.of("/spectate").on("connection", () => {
  // Spectators get a 5-s delayed stream (Sprint 3).
});

httpServer.listen(PORT, () => {
  console.log(`vmsg-game-server listening on :${PORT}`);
  console.log(`events: ${Object.values(WS_EVENTS).join(", ")}`);
});
