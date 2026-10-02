// Bundles installer/src/main.tsx into ../install.js (single file, no node_modules needed at runtime).
import { build, context } from "esbuild";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const watch = process.argv.includes("--watch");

// Ink imports react-devtools-core behind a DEV=true check; the bundle never needs it.
const stubDevtools = {
  name: "stub-react-devtools",
  setup(b) {
    b.onResolve({ filter: /^react-devtools-core$/ }, (args) => ({ path: args.path, namespace: "stub" }));
    b.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ contents: "export default {};", loader: "js" }));
  },
};

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  platform: "node",
  target: "node20",
  format: "esm",
  outfile: "../install.js",
  minify: false,
  legalComments: "none",
  jsx: "automatic",
  plugins: [stubDevtools],
  define: { "process.env.INSTALLER_VERSION": JSON.stringify(pkg.version) },
  banner: {
    js: [
      "#!/usr/bin/env node",
      "// GENERATED FILE — do not edit. Source: installer/src (build with `npm run build` in installer/).",
      "// Node 20+ required. The plugin's Python skills still need Python 3.10+; this file only installs them.",
      "const __major = Number(process.versions.node.split('.')[0]);",
      "if (__major < 20) { process.stderr.write(`install.js: Node.js 20 or newer is required (found ${process.versions.node}); install it from https://nodejs.org\\n`); process.exit(1); }",
      "import { createRequire as __createRequire } from 'node:module';",
      "const require = __createRequire(import.meta.url);",
    ].join("\n"),
  },
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
