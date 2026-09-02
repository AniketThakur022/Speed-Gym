import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { safeLocalStorage } from "@/lib/browser";

type User = {
  id: string;
  name: string;
  email: string;
  role: string;
};

type AuthState = {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isOnboarded: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithFirebase: (idToken: string, method: "google" | "phone") => Promise<void>;
  logout: () => void;
  setToken: (token: string | null) => void;
  setRefreshToken: (token: string | null) => void;
  completeOnboarding: () => void;
};

const IS_MOCK = process.env.NEXT_PUBLIC_API_MOCK !== "false";

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      refreshToken: null,
      isAuthenticated: false,
      isOnboarded: false,

      login: async (email: string, _password: string) => {
        if (IS_MOCK) {
          await new Promise((r) => setTimeout(r, 300));
          set({
            user: { id: "1", name: email.split("@")[0], email, role: "Champion" },
            token: "mock-jwt-token",
            isAuthenticated: true,
          });
        } else {
          // BASE_URL matters in the Capacitor/TWA shells: the app origin serves
          // static files, so a bare "/api/v1" path would never reach the backend.
          const API_PREFIX = `${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1`;
          const res = await fetch(`${API_PREFIX}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password: _password }),
          });
          if (!res.ok) throw new Error("Login failed");
          const data = await res.json();
          // refreshToken persisted (the recovered source dropped it here, so a
          // password login could never refresh — only the Firebase path stored it).
          set({
            user: data.user,
            token: data.token,
            refreshToken: data.refreshToken,
            isAuthenticated: true,
          });
        }
      },

      loginWithFirebase: async (idToken: string, method: "google" | "phone") => {
        if (IS_MOCK) {
          await new Promise((r) => setTimeout(r, 300));
          const name = method === "google" ? "Firebase User" : "Phone User";
          set({
            user: { id: "1", name, email: `${name}@firebase.com`, role: "Champion" },
            token: "mock-firebase-token",
            isAuthenticated: true,
          });
        } else {
          const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1/auth/${method}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ idToken }),
          });
          if (!res.ok) throw new Error("Firebase auth failed");
          const data = await res.json();
          set({ user: data.user, token: data.token, refreshToken: data.refreshToken, isAuthenticated: true });
        }
      },

      logout: () => {
        set({ user: null, token: null, refreshToken: null, isAuthenticated: false });
      },

      setToken: (token) => {
        set({ token, isAuthenticated: !!token });
      },

      setRefreshToken: (refreshToken) => {
        set({ refreshToken });
      },

      completeOnboarding: () => {
        set({ isOnboarded: true });
      },
    }),
    {
      name: "exam-arena-auth",
      storage: createJSONStorage(() => safeLocalStorage),
    },
  ),
);
