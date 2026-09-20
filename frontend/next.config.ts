import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Slim, self-contained production image: only the files each page
  // actually needs get copied into .next/standalone (see frontend/Dockerfile).
  // Only for that Docker build though - Vercel sets its own VERCEL env var
  // during builds, and its build pipeline expects the default output shape.
  // "standalone" skips generating files Vercel's own packaging step looks
  // for (next-server.js.nft.json), which fails the build with an ENOENT.
  output: process.env.VERCEL ? undefined : "standalone",
};

export default nextConfig;
