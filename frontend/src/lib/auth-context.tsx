"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import * as api from "./api-client";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    full_name?: string;
    organization_name?: string;
  }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const loadUser = useCallback(async () => {
    if (!api.getAccessToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.fetchMe();
      setUser(me);
    } catch {
      api.clearTokens();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Genuine fetch-on-mount (validate the stored token against the API) —
    // there's no external system to subscribe to here, just a one-time
    // async call, so the lint rule's "subscribe instead" suggestion doesn't
    // apply.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUser();
    const onUnauthorized = () => {
      setUser(null);
      router.push("/login");
    };
    window.addEventListener("lumen:unauthorized", onUnauthorized);
    return () => window.removeEventListener("lumen:unauthorized", onUnauthorized);
  }, [loadUser, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      await api.login(email, password);
      await loadUser();
    },
    [loadUser]
  );

  const register = useCallback(
    async (input: { email: string; password: string; full_name?: string; organization_name?: string }) => {
      await api.register(input);
      await api.login(input.email, input.password);
      await loadUser();
    },
    [loadUser]
  );

  const logout = useCallback(() => {
    api.logout();
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
