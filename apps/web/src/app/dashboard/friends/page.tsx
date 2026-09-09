"use client";

/** Friends: request by email, accept/decline, and in-person QR pairing
 *  (one-time, 5-minute signed codes). Parent-managed for kids accounts. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFriends, qrGenerate, qrRedeem, requestFriend, respondFriend } from "@/services/social";
import { usePolicyStore } from "@/stores/policy-store";

export default function FriendsPage() {
  const policy = usePolicyStore((s) => s.policy);
  const friends = useQuery({ queryKey: ["friends"], queryFn: getFriends });
  const [email, setEmail] = useState("");
  const [code, setCode] = useState<{ code: string; sig: string; expiresIn: number } | null>(null);
  const [redeem, setRedeem] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setNotice(ok); void friends.refetch(); } catch (err) { setNotice(err instanceof Error ? err.message : "Something went wrong"); }
  };

  if (policy.friends === "parent_managed") {
    return <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8"><h1 className="text-fluid-xl font-semibold">Friends</h1><p className="mt-2 text-fluid-sm text-muted-foreground">Friends on kids accounts are managed by a parent.</p></main>;
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">
      <h1 className="text-fluid-xl font-semibold">Friends</h1>
      {notice && <p role="status" aria-live="polite" className="mt-3 rounded-lg bg-accent p-3 text-fluid-sm">{notice}</p>}
      <div className="mt-4 flex gap-2">
        <input className="flex-1 rounded-lg border border-border bg-background px-3 py-2" aria-label="Friend's email address" placeholder="friend@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button type="button" onClick={() => run(() => requestFriend(email), "Request sent")} className="rounded-lg bg-primary px-4 py-2 text-primary-foreground">Add</button>
      </div>
      <div className="mt-4 rounded-lg border border-border bg-card p-3 text-fluid-sm">
        <div className="flex items-center justify-between">
          <span>Pair in person</span>
          <button type="button" onClick={() => run(async () => setCode(await qrGenerate()), "Show this code to your friend")} className="underline">New code</button>
        </div>
        {code && <p className="mt-2 break-all font-mono text-fluid-xs">{code.code}.{code.sig.slice(0, 16)}… <span className="text-muted-foreground">(valid {Math.round(code.expiresIn / 60)} min, one use)</span></p>}
        <div className="mt-2 flex gap-2">
          <input className="flex-1 rounded-lg border border-border bg-background px-3 py-1" aria-label="Pairing code" placeholder="paste code.sig" value={redeem} onChange={(e) => setRedeem(e.target.value)} />
          <button type="button" onClick={() => { const [c, s] = redeem.split("."); void run(() => qrRedeem(c, s), "Paired!"); }} className="rounded-lg border border-border px-3">Redeem</button>
        </div>
      </div>
      {(friends.data?.incoming ?? []).map((f) => (
        <div key={f.friendship_id} className="mt-3 flex items-center justify-between rounded-lg border border-border p-3 text-fluid-sm">
          <span>{f.name} wants to be friends</span>
          <span className="flex gap-2">
            <button type="button" onClick={() => run(() => respondFriend(f.friendship_id, "accept"), "Accepted")} className="underline">Accept</button>
            <button type="button" onClick={() => run(() => respondFriend(f.friendship_id, "decline"), "Declined")} className="text-muted-foreground underline">Decline</button>
          </span>
        </div>
      ))}
      <ul className="mt-4 grid gap-1 text-fluid-sm">
        {(friends.data?.friends ?? []).map((f) => <li key={f.friendship_id} className="rounded-lg bg-card px-3 py-2">{f.name}</li>)}
        {friends.data && friends.data.friends.length === 0 && <li className="text-muted-foreground">No friends yet.</li>}
      </ul>
    </main>
  );
}
