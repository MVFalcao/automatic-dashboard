import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    const token = process.env.DASHBOARD_LOCAL_AUTH_TOKEN;
    return [
      {
        source: "/backend/:path*",
        destination: "http://127.0.0.1:8000/:path*",
        ...(token ? { headers: [{ key: "Authorization", value: `Bearer ${token}` }] } : {}),
      },
    ];
  },
};

export default nextConfig;
