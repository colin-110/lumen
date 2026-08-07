/**
 * Captures the README screenshots against a running Lumen instance.
 *
 *   cd frontend && node scripts/capture-screenshots.mjs [baseUrl] [email] [password] [apiUrl]
 *
 * Defaults to the local stack. Point it at a deployment to shoot that instead:
 *   cd frontend && node scripts/capture-screenshots.mjs https://your-host admin@enterprise.ai 'pw'
 *
 * Writes docs/screenshot-*.png. Re-runnable: it uploads its own fixture
 * documents (a contract and an invoice that deliberately disagree) and deletes
 * them afterwards, so it doesn't depend on — or pollute — whatever is already
 * in the instance.
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = (process.argv[2] || "http://localhost:3000").replace(/\/$/, "");
const EMAIL = process.argv[3] || "admin@enterprise.ai";
const PASSWORD = process.argv[4] || "admin12345";
// A deployment puts the API behind the same origin as the app (Caddy reverse
// proxies /api), but the local dev stack runs the backend on its own port.
// Overridable, because neither guess holds for every environment.
const API = (
  process.argv[5] ||
  (new URL(BASE).port === "3000" ? "http://localhost:8000/api/v1" : `${BASE}/api/v1`)
).replace(/\/$/, "");
// Relative to this file, not the cwd — playwright lives in frontend/node_modules,
// so the script is run from there while the output belongs at the repo root.
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs");

const CONTRACT = `Master Services Agreement - Northwind Ltd and Acme Corp

1. Fees and Charges
The agreed monthly fee is $4,500 USD, billed in arrears. The monthly fee covers
up to 10TB of aggregate egress traffic per calendar month. Any overage beyond
10TB is billed at $80 per TB, prorated to the nearest whole terabyte.

2. Payment Terms
Payment terms are NET 30 from invoice date. Invoices not disputed in writing
within 10 business days of receipt are deemed accepted in full. Late payments
accrue interest at 1.5% per month.

3. Service Levels
Northwind commits to 99.9% monthly uptime measured at the load balancer,
excluding scheduled maintenance notified 5 business days in advance.
`;

const INVOICE = `Invoice INV-8842 - Northwind Ltd

Bill to: Acme Corp
Billing period: March 2027
Managed hosting monthly fee: $4,500.00
Egress overage: 3 TB at $95.00 per TB = $285.00
Total due: $4,785.00
Payment terms: NET 15
`;

const shot = async (page, name) => {
  await page.screenshot({ path: path.join(OUT, `screenshot-${name}.png`), fullPage: false });
  console.log(`  captured docs/screenshot-${name}.png`);
};

async function api(token, route, init = {}) {
  const res = await fetch(`${API}${route}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...(init.headers || {}) },
  });
  return res;
}

async function main() {
  await mkdir(OUT, { recursive: true });

  // --- auth via the API, so the browser starts already signed in ----------
  const loginRes = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: EMAIL, password: PASSWORD }),
  });
  if (!loginRes.ok) throw new Error(`login failed (${loginRes.status}) — check credentials`);
  const { access_token, refresh_token } = await loginRes.json();

  // --- fixture documents ---------------------------------------------------
  // Named the way a real corpus is named, not "contract.txt": the empty state
  // builds its suggested questions out of the filenames it finds, so terse
  // fixture names would make the hero shot read as a toy.
  const uploaded = [];
  for (const [filename, body] of [
    ["master_services_agreement.txt", CONTRACT],
    ["invoice_INV-8842.txt", INVOICE],
  ]) {
    const form = new FormData();
    form.append("file", new Blob([body], { type: "text/plain" }), filename);
    const res = await api(access_token, "/documents/upload", { method: "POST", body: form });
    if (!res.ok) throw new Error(`upload ${filename} failed (${res.status})`);
    uploaded.push(await res.json());
  }
  console.log("  uploaded 2 fixture documents, waiting for ingestion...");
  // Failing loudly matters: this loop used to fall through silently on
  // timeout, and the run happily shot an empty state reading "No documents
  // yet" and a chat answering "no documents were provided" — screenshots that
  // looked like a broken product rather than a stalled worker.
  let ingested = false;
  let lastStatus = "unknown";
  for (let i = 0; i < 60 && !ingested; i++) {
    const docs = await (await api(access_token, "/documents/")).json();
    const mine = docs.filter((d) => uploaded.some((u) => u.id === d.id));
    lastStatus = mine.map((d) => `${d.filename}=${d.status}`).join(", ") || "not listed";
    ingested = mine.length === 2 && mine.every((d) => d.status === "completed");
    if (!ingested) await new Promise((r) => setTimeout(r, 2000));
  }
  if (!ingested) {
    throw new Error(
      `documents never finished ingesting after 120s (${lastStatus}). ` +
        `Is the Celery worker running? \`docker compose up -d worker\``
    );
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2, // retina-quality for a README
    colorScheme: "dark",
  });

  // Seed tokens before any page script runs, so the app boots authenticated.
  await context.addInitScript(
    ([a, r]) => {
      localStorage.setItem("lumen_access_token", a);
      localStorage.setItem("lumen_refresh_token", r);
    },
    [access_token, refresh_token]
  );

  const page = await context.newPage();
  const settle = async (ms = 1200) => {
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(ms);
  };

  // --- 1. documents ---------------------------------------------------------
  await page.goto(`${BASE}/documents`, { waitUntil: "domcontentloaded" });
  await settle();
  await shot(page, "documents");

  // --- 2. the empty state ---------------------------------------------------
  // Shot before anything is asked, because that's the first thing a visitor
  // sees, and because the suggested questions are generated from the two
  // fixture documents above — proof they aren't a hardcoded list.
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await settle();
  await shot(page, "chat-empty");

  // --- 3. chat with a cited, multi-document answer --------------------------
  const composer = page.getByPlaceholder(/Ask anything/i);
  await composer.fill("Does the invoice match the contract on payment terms and the overage rate?");
  await page.getByRole("button", { name: /send message/i }).click();
  // Wait for the streamed answer rather than a fixed sleep.
  await page
    .locator("text=/conflict|does not match|NET 15|NET 30/i")
    .first()
    .waitFor({ timeout: 120_000 })
    .catch(() => console.log("  (no answer text matched — capturing whatever rendered)"));
  await settle(1500);
  const quotaVisible = await page
    .locator("text=/quota exhausted/i")
    .first()
    .isVisible()
    .catch(() => false);
  await shot(page, quotaVisible ? "quota-error" : "chat");
  if (quotaVisible) {
    console.log("  NOTE: provider quota is spent, so this run captured the quota");
    console.log("        notice instead of an answer. Re-run once quota resets to");
    console.log("        get docs/screenshot-chat.png.");
  }

  // --- 4. retrieval debugger ------------------------------------------------
  await page.goto(`${BASE}/debug`, { waitUntil: "domcontentloaded" });
  await settle();
  await page.getByPlaceholder(/Ask something/i).fill("What are the payment terms and the overage rate?");
  await page.getByRole("button", { name: /^trace$/i }).click();
  await page.locator("text=/Cross-encoder rerank/i").first().waitFor({ timeout: 120_000 }).catch(() => {});
  await settle(1200);
  await shot(page, "debugger");

  // The rerank and selection stages — where the score floor drops candidates —
  // are the reason this view exists, and they sit below the fold.
  await page
    .locator("text=/Selected for the prompt/i")
    .first()
    .scrollIntoViewIfNeeded()
    .catch(() => {});
  await settle(800);
  await shot(page, "debugger-rerank");

  await browser.close();

  // --- cleanup --------------------------------------------------------------
  for (const doc of uploaded) {
    await api(access_token, `/documents/${doc.id}`, { method: "DELETE" });
  }
  console.log("  removed fixture documents");
}

main().catch((err) => {
  console.error("capture failed:", err.message);
  process.exit(1);
});
