import { db } from "./db";
import { useNetworkStore, type QueuedMutation } from "@/stores/network-store";

export async function cacheQueryData(key: string, data: unknown, trustStatus?: string): Promise<void> {
  await db.dashboardCache.put({
    id: key,
    data,
    updatedAt: Date.now(),
    trustStatus,
    ttl: trustStatus === "trusted" ? 86_400_000 : trustStatus === "sandbox" ? 3_600_000 : undefined,
  });
}

export async function getCachedQueryData(key: string): Promise<unknown | null> {
  const entry = await db.dashboardCache.get(key);
  if (!entry) return null;
  if (entry.ttl && Date.now() - entry.updatedAt > entry.ttl) {
    await db.dashboardCache.delete(key);
    return null;
  }
  return entry.data;
}

export async function clearExpiredCache(): Promise<void> {
  const now = Date.now();
  const expired = await db.dashboardCache
    .filter((e) => e.ttl !== undefined && now - e.updatedAt > e.ttl!)
    .toArray();
  await Promise.all(expired.map((e) => db.dashboardCache.delete(e.id)));
}

export async function syncAll(): Promise<void> {
  const queue = useNetworkStore.getState().syncQueue;
  if (!queue.length) return;

  const { removeFromQueue } = useNetworkStore.getState();
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

  const results = await Promise.allSettled(
    queue.map(async (mutation: QueuedMutation) => {
      const res = await fetch(`${API_URL}/api/v1/sync/${mutation.key}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mutation.payload),
      });
      if (!res.ok) throw new Error(`Sync failed for ${mutation.key}: ${res.status}`);
      return mutation;
    }),
  );

  for (const result of results) {
    if (result.status === "fulfilled") {
      const mutation = result.value;
      removeFromQueue(mutation.id);
      if (mutation.key === "content/feedback") {
        await db.feedbackQueue.delete(mutation.id);
      }
    }
  }
}
