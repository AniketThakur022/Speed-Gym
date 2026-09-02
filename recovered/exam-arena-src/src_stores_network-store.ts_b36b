import { create } from "zustand";

export type QueuedMutation = {
  id: string;
  key: string;
  payload: unknown;
  timestamp: number;
};

type NetworkState = {
  isOnline: boolean;
  syncQueue: QueuedMutation[];
  setOnline: (online: boolean) => void;
  addToQueue: (mutation: QueuedMutation) => void;
  removeFromQueue: (id: string) => void;
  clearQueue: () => void;
};

export const useNetworkStore = create<NetworkState>((set) => ({
  isOnline: true,
  syncQueue: [],
  setOnline: (online) => set({ isOnline: online }),
  addToQueue: (mutation) =>
    set((s) => ({ syncQueue: [...s.syncQueue, mutation] })),
  removeFromQueue: (id) =>
    set((s) => ({ syncQueue: s.syncQueue.filter((m) => m.id !== id) })),
  clearQueue: () => set({ syncQueue: [] }),
}));
