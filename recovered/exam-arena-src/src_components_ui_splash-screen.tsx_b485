"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { Swords } from "lucide-react";

export function SplashScreen({ onComplete }: { onComplete?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(el, { autoAlpha: 1 }, { autoAlpha: 0, duration: 0.6, delay: 1.8, ease: "power2.inOut", onComplete });
    }, el);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div ref={ref} className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-background">
      <Swords className="size-16 text-primary mb-4" />
      <h1 className="text-2xl font-bold text-white">Exam Arena</h1>
      <p className="text-muted-foreground text-sm mt-1">Arena of Champions</p>
    </div>
  );
}
