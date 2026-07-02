import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone output ships a self-contained server bundle for a slim Docker image.
  output: "standalone",
  // Proxy to the backend for API calls so we don't need CORS. Runs server-side,
  // so in Docker this targets the backend container (http://mcp:8000).
  async rewrites() {
    const apiUrl =
      process.env.REKALL_API_URL ||
      process.env.NEXT_PUBLIC_REKALL_API_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${apiUrl}/health`,
      },
    ];
  },
};

export default nextConfig;
