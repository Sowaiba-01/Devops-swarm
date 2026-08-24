/** @type {import('next').NextConfig} */
const nextConfig = {
  // Self-contained build: the runtime image copies .next/standalone and needs
  // no node_modules, which keeps the image around 120MB instead of ~600MB.
  output: "standalone",

  reactStrictMode: true,
  poweredByHeader: false,

  // Pin the workspace root. Turbopack otherwise walks up looking for a lockfile
  // and can latch onto an unrelated one outside the repository.
  turbopack: {
    root: __dirname,
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
