/** @type {import('next').NextConfig} */
const nextConfig = {
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
