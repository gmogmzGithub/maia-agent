import type { NextConfig } from "next";

const config: NextConfig = {
  agentRules: false,
  output: "standalone",
  experimental: { proxyClientMaxBodySize: "260mb" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/api/:path*` }];
  },
};
export default config;
