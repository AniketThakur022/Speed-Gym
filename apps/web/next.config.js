/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export", // static export — wrapped by Capacitor/TWA shells
  transpilePackages: [
    "@vmsg/shared-types",
    "@vmsg/psychometrics",
    "@vmsg/vedic-math",
    "@vmsg/design-tokens",
  ],
};

module.exports = nextConfig;
