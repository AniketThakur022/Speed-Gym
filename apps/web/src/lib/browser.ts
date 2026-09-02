export function getWindowWidth(fallback = 1024): number {
  if (typeof window === "undefined") return fallback;
  return window.innerWidth;
}

export function getWindowHeight(fallback = 768): number {
  if (typeof window === "undefined") return fallback;
  return window.innerHeight;
}

export const safeLocalStorage: Storage = {
  getItem(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  setItem(key: string, value: string): void {
    try { localStorage.setItem(key, value); } catch { }
  },
  removeItem(key: string): void {
    try { localStorage.removeItem(key); } catch { }
  },
  clear(): void {
    try { localStorage.clear(); } catch { }
  },
  get length(): number {
    try { return localStorage.length; } catch { return 0; }
  },
  key(index: number): string | null {
    try { return localStorage.key(index); } catch { return null; }
  },
};

export function createAudioContext(): AudioContext | null {
  try { return new AudioContext(); } catch { return null; }
}

