"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api-client";
import { AuthCard, FormField, inputClassName, submitButtonClassName } from "@/components/auth/AuthCard";

export default function RegisterPage() {
  const { register } = useAuth();
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      await register({
        email,
        password,
        full_name: fullName || undefined,
        organization_name: orgName || undefined,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCard
      title="Create your workspace"
      subtitle="Set up your organization's Lumen workspace"
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Full name">
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputClassName}
            placeholder="Ada Lovelace"
            autoComplete="name"
          />
        </FormField>
        <FormField label="Organization name">
          <input
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            className={inputClassName}
            placeholder="Acme Corp"
          />
        </FormField>
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
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClassName}
            placeholder="At least 8 characters"
          />
        </FormField>

        {error && <p className="rounded-xl bg-danger-bg px-3 py-2.5 text-xs text-danger">{error}</p>}

        <button type="submit" disabled={loading} className={submitButtonClassName}>
          {loading && <Loader2 size={15} className="animate-spin" />}
          Create account
        </button>
      </form>
    </AuthCard>
  );
}
