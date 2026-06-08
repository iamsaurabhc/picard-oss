/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_DEV_TEST_MODE: process.env.DEV_TEST_MODE ?? "",
  },
  reactStrictMode: true,
  output: "standalone",
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },
  experimental: {
    // Chat uses useSearchParams without a Suspense boundary during static analysis
    missingSuspenseWithCSRBailout: false,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Embedder-Policy", value: "require-corp" },
        ],
      },
      {
        source: "/libreoffice-wasm/:path*",
        headers: [{ key: "Cross-Origin-Resource-Policy", value: "cross-origin" }],
      },
    ];
  },
};

export default nextConfig;
