"use client";

import { useEffect, useState } from "react";

const suggestions = [
  "Quiero rentar una casa en Zapopan…",
  "Busco un depa que acepte mascotas…",
  "Quiero comprar una casa con jardín…",
  "Busco un terreno en Guadalajara…",
  "Un departamento hasta $25,000 al mes…",
];

export default function useSearchSuggestion(enabled: boolean) {
  const [suggestion, setSuggestion] = useState(suggestions[0]);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let rotation: ReturnType<typeof setInterval> | undefined;
    let typing: ReturnType<typeof setInterval> | undefined;

    function stop() {
      clearInterval(rotation);
      clearInterval(typing);
    }

    function start() {
      stop();
      setSuggestion(suggestions[0]);
      if (!enabled || motion.matches) return;
      let index = 0;
      rotation = setInterval(() => {
        clearInterval(typing);
        index = (index + 1) % suggestions.length;
        const letters = Array.from(suggestions[index]);
        let count = 0;
        setSuggestion("");
        typing = setInterval(() => {
          count += 1;
          setSuggestion(letters.slice(0, count).join(""));
          if (count === letters.length) clearInterval(typing);
        }, 32);
      }, 3000);
    }

    start();
    motion.addEventListener("change", start);
    return () => {
      stop();
      motion.removeEventListener("change", start);
    };
  }, [enabled]);

  return suggestion;
}
