import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // When deployed behind the OpenClaw platform proxy at /control/*, Next.js
  // needs to know its base path so it can load assets from /control/_next/
  // instead of /_next/. This is set via NEXT_PUBLIC_BASE_PATH env var.
  // For standalone deployment at root, leave NEXT_PUBLIC_BASE_PATH unset.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  // In dev, Next may proxy requests based on the request origin/host.
  // Allow common local origins so `next dev --hostname 127.0.0.1` works
  // when users access via http://localhost:3000 or http://127.0.0.1:3000.
  // Keep the LAN IP as well for dev on the local network.
  allowedDevOrigins: ["192.168.1.101", "localhost", "127.0.0.1"],
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
