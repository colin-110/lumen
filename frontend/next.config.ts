import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Slim, self-contained production image: only the files each page
  // actually needs get copied into .next/standalone (see frontend/Dockerfile).
  output: "standalone",
};

export default nextConfig;
