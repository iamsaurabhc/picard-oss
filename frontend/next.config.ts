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
};

export default nextConfig;
