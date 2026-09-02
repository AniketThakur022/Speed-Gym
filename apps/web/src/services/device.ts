type Platform = "web" | "android" | "ios";

let cachedPlatform: Platform = "web";

export function setPlatform(p: Platform) {
  cachedPlatform = p;
}

export function isOnline(): boolean {
  if (typeof navigator === "undefined") return true;
  return navigator.onLine;
}

type OnlineCallback = () => void;

export function onOnline(cb: OnlineCallback): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("online", cb);
  return () => window.removeEventListener("online", cb);
}

export function onOffline(cb: OnlineCallback): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("offline", cb);
  return () => window.removeEventListener("offline", cb);
}
