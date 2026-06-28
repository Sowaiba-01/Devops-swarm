/** @type {import('next').NextConfig} */
const nextConfig = {
  // 'standalone' creates a self-contained build inside .next/standalone/
  // The Docker image copies that folder so it doesn't need node_modules.
  // Result: much smaller production images (~100MB vs ~600MB).
  output: "standalone",
};

module.exports = nextConfig;
