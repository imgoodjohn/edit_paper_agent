/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export so FastAPI can serve the built site without Node at runtime.
  output: 'export',
  // Each route is a folder with index.html -- friendlier for FastAPI's
  // StaticFiles + a /sessions/{sid}/ catch-all rewrite.
  trailingSlash: true,
  // next/image's default loader needs a Node server; disable optimisation
  // so <Image> falls back to plain <img> in the static export.
  images: { unoptimized: true },
  // Don't fail the production build on lint / type warnings -- we just want
  // a runnable bundle for the user. They can still see issues in dev.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
}

export default nextConfig
