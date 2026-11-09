// Build the sole browser entry point into the server-served IIFE at web/dist.
// Reruns overwrite generated JS; edit web/ts, never the bundle. This is compilation,
// not a server launch or inference call. package.json invokes it via npm run build;
// npm run typecheck separately checks strict, no-emit browser contracts in tsconfig.json.
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
