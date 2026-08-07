import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LLMErrorNotice } from "./LLMErrorNotice";
import type { LLMError, LLMErrorKind } from "@/lib/types";

const err = (kind: LLMErrorKind, over: Partial<LLMError> = {}): LLMError => ({
  kind,
  message: "something happened",
  retry_after_seconds: null,
  retryable: false,
  detail: null,
  ...over,
});

describe("LLMErrorNotice", () => {
  it("names quota exhaustion explicitly", () => {
    render(<LLMErrorNotice error={err("quota", { message: "Your quota is used up" })} />);
    expect(screen.getByText(/quota exhausted/i)).toBeInTheDocument();
    expect(screen.getByText("Your quota is used up")).toBeInTheDocument();
  });

  it("does not blame the API key when the cause is quota", () => {
    // The original bug: every failure said "check that an API key is configured".
    render(<LLMErrorNotice error={err("quota", { message: "Your provider quota is used up." })} />);
    expect(screen.getByRole("alert").textContent).not.toMatch(/rejected the API key/i);
  });

  it("distinguishes an auth failure from a quota failure", () => {
    render(<LLMErrorNotice error={err("auth")} />);
    expect(screen.getByText(/rejected the API key/i)).toBeInTheDocument();
  });

  it("shows the provider's suggested retry delay when present", () => {
    render(<LLMErrorNotice error={err("rate_limit", { retry_after_seconds: 38, retryable: true })} />);
    expect(screen.getByText(/~38s/)).toBeInTheDocument();
  });

  it("omits the retry hint when the provider gave no delay", () => {
    render(<LLMErrorNotice error={err("unknown")} />);
    expect(screen.queryByText(/retrying in/i)).not.toBeInTheDocument();
  });

  it("keeps the raw provider response collapsed until asked for", async () => {
    const user = userEvent.setup();
    render(<LLMErrorNotice error={err("quota", { detail: "RESOURCE_EXHAUSTED verbose blob" })} />);
    expect(screen.queryByText(/RESOURCE_EXHAUSTED/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /show provider response/i }));
    expect(screen.getByText(/RESOURCE_EXHAUSTED/)).toBeInTheDocument();
  });

  it("renders no details toggle when there is no detail", () => {
    render(<LLMErrorNotice error={err("timeout")} />);
    expect(screen.queryByRole("button", { name: /provider response/i })).not.toBeInTheDocument();
  });

  it("is announced to assistive tech", () => {
    render(<LLMErrorNotice error={err("quota")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("has a heading for every error kind", () => {
    const kinds: LLMErrorKind[] = [
      "quota",
      "rate_limit",
      "auth",
      "timeout",
      "unavailable",
      "context_length",
      "unknown",
    ];
    for (const k of kinds) {
      const { unmount } = render(<LLMErrorNotice error={err(k)} />);
      // Every kind must produce a non-empty heading, not fall through blank.
      expect(screen.getByRole("alert").textContent?.trim().length).toBeGreaterThan(10);
      unmount();
    }
  });
});
