const esbuild = require("esbuild");
const path = require("node:path");
esbuild.build({
  entryPoints: [path.join(__dirname, "..", "web", "ts", "console.ts")],
  outfile: path.join(__dirname, "..", "web", "dist", "console.js"),
  bundle: true,
  target: "es2020",
  format: "iife",
  sourcemap: false,
  minify: true,
}).catch(() => process.exit(1));
