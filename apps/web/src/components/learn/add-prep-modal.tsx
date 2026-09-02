"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import gsap from "gsap";
import { X, GraduationCap, Calculator, BookOpen, Landmark, Check, AlertCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { useDashboardData } from "@/hooks/queries/use-dashboard";

const EXAMS = [
  { id: "cat", label: "CAT", icon: GraduationCap },
  { id: "gmat", label: "GMAT", icon: Calculator },
  { id: "gre", label: "GRE", icon: BookOpen },
  { id: "banking", label: "Banking", icon: Landmark },
];

function getStatus(value: number): { label: string; color: string; bgClass: string } {
  if (value >= 80) return { label: "Strong", color: "text-primary", bgClass: "bg-primary/10" };
  if (value >= 50) return { label: "In Progress", color: "text-chart-3", bgClass: "bg-chart-3/10" };
  return { label: "Needs Work", color: "text-destructive", bgClass: "bg-destructive/10" };
}

type Props = { onClose: () => void };

export function AddPrepModal({ onClose }: Props) {
  const [selectedExam, setSelectedExam] = useState<string | null>(null);
  const addActivePrep = useOnboardingStore((s) => s.addActivePrep);
  const activePreps = useOnboardingStore((s) => s.activePreps);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const { data } = useDashboardData(selectedExam ?? undefined);
  const topics = data?.topics ?? [];

  useEffect(() => {
    if (overlayRef.current && dialogRef.current) {
      gsap.fromTo(overlayRef.current, { opacity: 0 }, { opacity: 1, duration: 0.2 });
      gsap.fromTo(dialogRef.current, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.25, ease: "power2.out" });
    }
  }, []);

  const handleClose = () => {
    if (overlayRef.current && dialogRef.current) {
      gsap.to(dialogRef.current, { opacity: 0, y: 16, duration: 0.15 });
      gsap.to(overlayRef.current, { opacity: 0, duration: 0.15, onComplete: onClose });
    } else {
      onClose();
    }
  };

  const handleConfirm = () => {
    if (selectedExam && !activePreps.includes(selectedExam)) {
      addActivePrep(selectedExam);
    }
    handleClose();
  };

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        ref={dialogRef}
        className="w-full max-w-md max-h-[85vh] overflow-y-auto bg-card rounded-t-3xl sm:rounded-3xl border border-border/60 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-card/95 backdrop-blur-sm px-5 pt-5 pb-3 border-b border-border/40 flex items-center justify-between">
          <h2 className="text-fluid-base font-bold text-foreground">
            {selectedExam ? "Topic Mastery" : "Add Prep"}
          </h2>
          <button
            type="button"
            onClick={handleClose}
            className="grid size-8 place-items-center rounded-lg text-muted-foreground/50 hover:text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          {!selectedExam ? (
            <div className="flex flex-col gap-2.5">
              <p className="text-fluid-xs text-muted-foreground/60 mb-1">
                Choose an exam or subject to see your progress
              </p>
              {EXAMS.map((exam) => {
                const Icon = exam.icon;
                const alreadyAdded = activePreps.includes(exam.id);
                return (
                  <button
                    key={exam.id}
                    type="button"
                    onClick={() => setSelectedExam(exam.id)}
                    className={cn(
                      "flex items-center gap-3 rounded-2xl border p-4 outline-none transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring",
                      alreadyAdded
                        ? "border-primary/40 bg-primary/5"
                        : "border-border/60 bg-background hover:border-border hover:bg-accent/40",
                    )}
                  >
                    <span className="grid size-10 place-items-center rounded-xl border border-border/40 bg-muted/50">
                      <Icon size={18} className="text-muted-foreground/70" />
                    </span>
                    <span className="flex-1 text-left text-fluid-sm font-bold text-foreground">
                      {exam.label}
                    </span>
                    {alreadyAdded && (
                      <span className="text-[10px] font-bold text-primary tracking-wide">ADDED</span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {topics.length === 0 ? (
                <div className="flex flex-col items-center py-8 text-center">
                  <p className="text-fluid-sm text-muted-foreground/60">No topic data available yet.</p>
                  <p className="text-fluid-xs text-muted-foreground/40 mt-1">Complete a sprint to see mastery levels.</p>
                </div>
              ) : (
                <>
                  <p className="text-fluid-xs text-muted-foreground/60 mb-1">
                    Here&apos;s where you stand:
                  </p>
                  {topics.map((topic) => {
                    const status = getStatus(topic.value);
                    return (
                      <div
                        key={topic.name}
                        className="rounded-xl border border-border/40 bg-background p-4"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-fluid-sm font-bold text-foreground">
                            {topic.name}
                          </span>
                          <span className={cn("text-[10px] font-bold tracking-wide", status.color)}>
                            {status.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{
                                width: `${topic.value}%`,
                                backgroundColor: topic.value >= 80 ? "var(--primary)" : topic.value >= 50 ? "var(--chart-3)" : "var(--destructive)",
                              }}
                            />
                          </div>
                          <span className="text-fluid-xs font-mono text-muted-foreground/60 w-8 text-right">
                            {topic.value}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          )}
        </div>

        <div className="sticky bottom-0 bg-card/95 backdrop-blur-sm px-5 pb-5 pt-3 border-t border-border/40">
          {selectedExam ? (
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setSelectedExam(null)}
                className="flex-1 rounded-2xl border border-border/60 bg-background py-3.5 text-fluid-sm font-bold text-foreground/80 outline-none transition-all hover:bg-accent/40 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring"
              >
                Back
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                className="flex-1 rounded-2xl bg-primary py-3.5 text-fluid-sm font-bold text-primary-foreground outline-none transition-all hover:opacity-90 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring"
              >
                Confirm
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleClose}
              className="w-full rounded-2xl border border-border/60 bg-background py-3.5 text-fluid-sm font-bold text-foreground/80 outline-none transition-all hover:bg-accent/40 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
