"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api-client";
import { AuthCard, FormField, inputClassName, submitButtonClassName } from "@/components/auth/AuthCard";

// Opt-in only: a deployment sets these two build-time env vars to pre-fill
// the login form with a demo account's credentials (e.g. so a recruiter can
// sign in with one click instead of needing credentials handed to them).
// Empty/unset by default, so a normal deployment's login form stays blank.
const DEMO_EMAIL = process.env.NEXT_PUBLIC_DEMO_EMAIL ?? "";
const DEMO_PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCard
      title="Welcome back"
      subtitle="Sign in to your Lumen workspace"
      footer={
        <>
          Don&apos;t have an account?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Email">
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClassName}
            placeholder="you@company.com"
          />
        </FormField>
        <FormField label="Password">
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClassName}
            placeholder="••••••••"
          />
        </FormField>

        {error && (
          <p className="rounded-xl bg-danger-bg px-3 py-2.5 text-xs text-danger">{error}</p>
        )}

        <button type="submit" disabled={loading} className={submitButtonClassName}>
          {loading && <Loader2 size={15} className="animate-spin" />}
          Sign in
        </button>
      </form>
    </AuthCard>
  );
}
