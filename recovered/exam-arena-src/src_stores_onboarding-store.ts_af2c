import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { safeLocalStorage } from "@/lib/browser";

type OnboardingState = {
  currentStep: number;
  name: string;
  email: string;
  phone: string;
  authMethod: "google" | "phone" | null;
  targetExam: string;
  level: string;
  isOnboarded: boolean;
  autoSlidePaused: boolean;
  firstName: string;
  persona: string | null;
  goal: string | null;
  triggers: string[];
  sex: string | null;
  dob: { day: number; month: string; year: number };
  activePreps: string[];

  setAuthData: (data: { name?: string; email?: string; phone?: string; authMethod: "google" | "phone" }) => void;
  setTargetExam: (exam: string) => void;
  setLevel: (level: string) => void;
  nextStep: () => void;
  completeOnboarding: () => void;
  finishOnboarding: () => void;
  reset: () => void;
  setAutoSlidePaused: (paused: boolean) => void;
  setFirstName: (name: string) => void;
  setPersona: (persona: string | null) => void;
  setGoal: (goal: string | null) => void;
  toggleTrigger: (trigger: string) => void;
  setSex: (sex: string | null) => void;
  setDob: (dob: { day: number; month: string; year: number }) => void;
  addActivePrep: (prep: string) => void;
};

const initial = {
  currentStep: 0,
  name: "",
  email: "",
  phone: "",
  authMethod: null as "google" | "phone" | null,
  targetExam: "",
  level: "",
  isOnboarded: false,
  autoSlidePaused: false,
  firstName: "",
  persona: null as string | null,
  goal: null as string | null,
  triggers: [] as string[],
  sex: null as string | null,
  dob: { day: 1, month: "January", year: 2000 },
  activePreps: [] as string[],
};

export const useOnboardingStore = create<OnboardingState>()(
  persist(
    (set) => ({
      ...initial,

      setAuthData: (data) =>
        set((s) => ({
          ...s,
          name: data.name ?? s.name,
          email: data.email ?? s.email,
          phone: data.phone ?? s.phone,
          authMethod: data.authMethod,
        })),

      setTargetExam: (exam) => set({ targetExam: exam }),
      setLevel: (level) => set({ level }),

      nextStep: () => set((s) => ({ currentStep: s.currentStep + 1 })),

      completeOnboarding: () => set({ isOnboarded: true }),

      reset: () => set(initial),

      setAutoSlidePaused: (paused: boolean) => set({ autoSlidePaused: paused }),

      setFirstName: (name) => set({ firstName: name }),
      setPersona: (persona) => set({ persona }),
      setGoal: (goal) => set({ goal }),
      toggleTrigger: (trigger) =>
        set((s) => ({
          triggers: s.triggers.includes(trigger)
            ? s.triggers.filter((t) => t !== trigger)
            : [...s.triggers, trigger],
        })),
      setSex: (sex) => set({ sex }),
      setDob: (dob) => set({ dob }),
      addActivePrep: (prep) =>
        set((s) => ({
          activePreps: s.activePreps.includes(prep)
            ? s.activePreps
            : [...s.activePreps, prep],
        })),
      finishOnboarding: () => set({ isOnboarded: true }),
    }),
    {
      name: "exam-arena-onboarding",
      storage: createJSONStorage(() => safeLocalStorage),
    },
  ),
);
