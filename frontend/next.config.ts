import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["31.97.20.32"],
  typescript: {
    ignoreBuildErrors: true,
  },
  serverExternalPackages: ["ffmpeg-static"],
};

export default nextConfig;
