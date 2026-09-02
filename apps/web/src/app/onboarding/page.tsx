"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { Flame, Globe, Smartphone, Zap, Target, Trophy, Swords } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useRouter } from "next/navigation";

const FEATURES = [
  { icon: Zap, label: "Speed Drills", color: "#C8FF5A" },
  { icon: Target, label: "Smart Sprints", color: "#22D3EE" },
  { icon: Trophy, label: "Live Rankings", color: "#FBBF24" },
];

export default function OnboardingPage() {
  const authLogin = useAuthStore((s) => s.login);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const router = useRouter();

  const heroRef = useRef<HTMLDivElement>(null);
  const brandRef = useRef<HTMLDivElement>(null);
  const taglineRef = useRef<HTMLDivElement>(null);
  const featuresRef = useRef<HTMLDivElement>(null);
  const buttonsRef = useRef<HTMLDivElement>(null);
  const footerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isAuthenticated) return;

    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

    tl.fromTo(
      brandRef.current,
      { opacity: 0, y: -20, scale: 0.9 },
      { opacity: 1, y: 0, scale: 1, duration: 0.3 },
    )
      .fromTo(
        taglineRef.current,
        { opacity: 0, y: 16 },
        { opacity: 1, y: 0, duration: 0.25 },
        "-=0.2",
      )
      .fromTo(
        featuresRef.current?.children ? Array.from(featuresRef.current.children) : [],
        { opacity: 0, y: 20, scale: 0.9 },
        { opacity: 1, y: 0, scale: 1, duration: 0.2, stagger: 0.05 },
        "-=0.15",
      )
      .fromTo(
        buttonsRef.current?.children ? Array.from(buttonsRef.current.children) : [],
        { opacity: 0, y: 16 },
        { opacity: 1, y: 0, duration: 0.2, stagger: 0.04 },
        "-=0.1",
      )
      .fromTo(
        footerRef.current,
        { opacity: 0 },
        { opacity: 1, duration: 0.2 },
        "-=0.1",
      );

    return () => { tl.kill(); };
  }, [isAuthenticated]);

  if (isAuthenticated) return <div className="fixed inset-0 bg-background" />;

  const handleLogin = (method: "google" | "phone") => {
    const name = method === "google" ? "Google User" : "Phone User";

    gsap.to(buttonsRef.current, {
      opacity: 0,
      y: 10,
      duration: 0.2,
      ease: "power2.in",
      onComplete: async () => {
        await authLogin(`${name}@exam.com`, "mock-password");
        router.replace("/dashboard");
      },
    });
  };

  return (
    <main className="relative flex h-dvh flex-col items-center justify-between bg-background overflow-hidden max-w-5xl mx-auto">
      {/* Background ambient glow */}
      <div className="pointer-events-none absolute inset-0">
        <div
          className="absolute top-[-20%] left-1/2 -translate-x-1/2 h-[500px] w-[500px] rounded-full opacity-[0.07]"
          style={{ background: "radial-gradient(circle, #C8FF5A 0%, transparent 70%)" }}
        />
        <div
          className="absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full opacity-[0.04]"
          style={{ background: "radial-gradient(circle, #22D3EE 0%, transparent 70%)" }}
        />
        <div
          className="absolute bottom-0 right-1/4 h-[300px] w-[300px] rounded-full opacity-[0.04]"
          style={{ background: "radial-gradient(circle, #A855F7 0%, transparent 70%)" }}
        />
      </div>

      {/* Hero */}
      <div ref={heroRef} className="relative flex flex-1 flex-col items-center justify-center px-6 w-full">
        {/* Brand */}
        <div ref={brandRef} className="flex flex-col items-center gap-4 mb-8">
          <div className="relative">
            <div className="grid size-16 place-items-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
              <Swords size={32} className="text-primary" />
            </div>
            <div className="absolute -inset-2 rounded-3xl bg-primary/5 blur-xl" />
          </div>
          <div className="text-center">
            <h1 className="text-3xl font-black tracking-[0.15em] text-foreground">
              EXAM ARENA
            </h1>
            <div className="flex items-center justify-center gap-2 mt-1.5">
              <div className="h-px w-6 bg-primary/30" />
              <span className="text-[10px] font-bold tracking-[0.3em] text-primary/60">
                ARENA OF CHAMPIONS
              </span>
              <div className="h-px w-6 bg-primary/30" />
            </div>
          </div>
        </div>

        {/* Tagline */}
        <div ref={taglineRef} className="text-center mb-10 max-w-xs">
          <p className="text-sm leading-relaxed text-muted-foreground/70">
            Not a coaching app.
            <br />
            <span className="text-foreground/90 font-semibold">
              A competitive battlefield
            </span>{" "}
            where India&apos;s sharpest minds fight, rank, and rise.
          </p>
        </div>

        {/* Feature pills */}
        <div ref={featuresRef} className="flex items-center gap-3 mb-12">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <div
                key={f.label}
                className="flex items-center gap-2 rounded-full border border-border/40 bg-card/60 backdrop-blur-sm px-3.5 py-2"
              >
                <Icon size={13} style={{ color: f.color }} />
                <span className="text-[11px] font-semibold text-muted-foreground/70">
                  {f.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* Auth buttons */}
        <div ref={buttonsRef} className="flex flex-col gap-3 w-full max-w-xs">
          <button
            type="button"
            onClick={() => handleLogin("google")}
            className="group flex items-center justify-center gap-3 rounded-2xl border border-border/60 bg-card px-5 py-4 text-sm font-bold text-foreground outline-none transition-all hover:border-primary/30 hover:bg-accent/30 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="grid size-8 place-items-center rounded-lg bg-white/10 group-hover:bg-white/15 transition-colors">
              <Globe size={16} className="text-foreground/80" />
            </span>
            Continue with Google
          </button>
          <button
            type="button"
            onClick={() => handleLogin("phone")}
            className="group flex items-center justify-center gap-3 rounded-2xl border border-border/60 bg-card px-5 py-4 text-sm font-bold text-foreground outline-none transition-all hover:border-primary/30 hover:bg-accent/30 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="grid size-8 place-items-center rounded-lg bg-white/10 group-hover:bg-white/15 transition-colors">
              <Smartphone size={16} className="text-foreground/80" />
            </span>
            Continue with Phone
          </button>
        </div>
      </div>

      {/* Footer */}
      <div ref={footerRef} className="relative pb-8 pt-4 text-center px-6">
        <p className="text-[11px] text-muted-foreground/40 leading-relaxed">
          By continuing, you agree to our{" "}
          <span className="text-muted-foreground/60 font-medium">Terms of Service</span>
          {" & "}
          <span className="text-muted-foreground/60 font-medium">Privacy Policy</span>
        </p>
      </div>
    </main>
  );
}
