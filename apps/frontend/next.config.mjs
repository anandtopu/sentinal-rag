/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // typedRoutes intentionally off: nav items are driven by a typed array
  // (see components/layout/sidebar.tsx) and the typed-routes generic doesn't
  // accept arbitrary string members. Re-enable with route literals if we
  // need link-time route validation in CI.
  // Proxy /api to the FastAPI backend in local dev. Production deployment
  // (Helm chart, Phase 7) routes through the same Ingress so this rewrite
  // is local-only.
  async rewrites() {
    if (process.env.NODE_ENV !== 'development') return [];
    return [
      {
        source: '/api/:path*',
        destination: `${
          (
            process.env.NEXT_PUBLIC_API_BASE_URL ??
            process.env.NEXT_PUBLIC_API_URL ??
            'http://localhost:8000/api/v1'
          ).replace(/\/$/, '')
        }/:path*`,
      },
    ];
  },
};

export default nextConfig;
