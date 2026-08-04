"use client";

import { useCallback, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "lumen_theme";

// Lazy initializer instead of an effect: the inline <head> script (see
// theme-script.ts) has already stamped data-theme on <html> by the time any
// component hydrates, so reading it synchronously at first render avoids an
// extra render pass instead of syncing it in afterward.
function readInitialTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  const setTheme = useCallback((next: Theme) => {
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggle };
}
