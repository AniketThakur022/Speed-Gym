# Sprint-1 auth — as implemented

Implements the memory `api-contract-v1`: the APK's frozen `/api/v1` shape on the
outside, the architecture doc's auth semantics on the inside. Restores the
behaviour proven by the pre-loss demo video (register/login, rotating refresh
tokens with replay detection, 300-s QR pairing).

Code: `services/api/app/security.py`, `services/api/app/routers/auth.py`,
`services/api/app/routers/webhooks.py`. Tests: `services/api/tests/test_auth.py`
(13/13 green against the dev stack; the suite skips itself when no stack is up).

## Endpoints

| Method + path | Behaviour |
|---|---|
| `POST /api/v1/auth/register` | 201 → `{user, token, refreshToken}`; 409 on duplicate email |
| `POST /api/v1/auth/login` | `{email, password}` → same shape; 401 on bad credentials |
| `POST /api/v1/auth/refresh` | `{refreshToken}` → new `{user, token, refreshToken}`; **rotates** |
| `POST /api/v1/auth/logout` | revokes the presented refresh token |
| `GET /api/v1/auth/me` | bearer-authenticated caller identity |
| `POST /api/v1/auth/scanner-login/generate` | `{code, sig, pollToken, expiresIn: 300}` |
| `POST /api/v1/auth/scanner-login/verify` | authenticated phone approves a code |
| `GET /api/v1/auth/scanner-login/poll` | pending → approved; issues tokens, burns the nonce |
| `POST /api/v1/auth/google`, `/auth/phone` | on contract, **501** until an IdP is configured |
| `POST /api/webhooks/{stripe,razorpay}` | provider-agnostic shells, **501** (owner decision pending) |

The client contract is satisfied without frontend edits: the recovered
`src/services/api.ts` reads `token` from the refresh response and retries once
on 401, which this implementation supports (the extra rotated `refreshToken`
field is additive).

## Token model

- **Access**: HS256 JWT, 15-minute TTL, claims `sub`/`tier`/`iat`/`exp`/`jti`.
  Signed with `JWT_SECRET`, shared with the Node game server as deploy-time
  config so the WebSocket handshake validates without a runtime call.
- **Refresh**: opaque 48-byte URL-safe secret. Stored **only** as SHA-256 in
  `refresh_tokens` (migration 60) alongside the device fingerprint.
- **Passwords**: stdlib `scrypt` (N=16384, r=8, p=1), per-password salt,
  constant-time comparison. No external hashing dependency.

## Replay detection

Every refresh mints a successor and stamps the consumed row's `rotated_to`.
Presenting an already-rotated token means the secret leaked, so the server
revokes **every active token sharing that device fingerprint**
(`revoke_reason = 'rotation_replay'`) and returns 401. The legitimate holder's
successor dies with the attacker's copy — re-authentication is required.

> **Caveat for future handlers that write-then-reject.** The revocation
> originally ran inside the request transaction and was silently rolled back by
> the `HTTPException`, leaving the successor token usable — detection logged, no
> enforcement. The handler now calls `conn.commit()` before raising. Any handler
> that must persist state *and* return an error needs the same treatment; the
> connection context manager rolls back on exception.

## QR scanner-login

`generate` issues a code plus an HMAC-SHA256 signature over it (`JWT_SECRET`)
and a separate `pollToken`, held in Redis at `qr:pair:{code}` with a 300-s TTL.
The signed-in device calls `verify` (signature checked, 400 on forgery); the
waiting device polls with its `pollToken` (403 on mismatch) and receives a full
token pair on approval. The key is deleted on collection, so the nonce is
strictly one-time; expiry or reuse returns 410.

## Deliberately not built yet

Payment providers stay stubbed until the owner picks Razorpay-first vs
Stripe-first — that choice sets default currency and webhook sticky-routing, and
the signature-verification seams (`verify_stripe_signature`,
`verify_razorpay_signature`) are where the real implementations land. Firebase
`google`/`phone` exchange is a pluggable IdP behind the frozen routes; wiring
Firebase Admin verification there is a config change, not a contract change.
