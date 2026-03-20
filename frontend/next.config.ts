import type { NextConfig } from "next";

// Allow extra dev origins via ALLOWED_DEV_ORIGINS env var (comma-separated).
const extraOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  // In dev, Next may proxy requests based on the request origin/host.
  // Allow common local origins so `next dev --hostname 0.0.0.0` works
  // when users access via any LAN IP, localhost, or 127.0.0.1.
  allowedDevOrigins: ["localhost", "127.0.0.1", ...extraOrigins],
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "img.clerk.com",
      },
    ],
  },
};

export default nextConfig;
