// Runs before `npm run build` (the "prebuild" script).
// Without it, a missing or partial `npm ci` shows up as confusing TypeScript
// errors ("Cannot find type definition file for 'vite/client'") whenever some
// other `tsc` is on the PATH. This turns that into one clear message.
import { existsSync, readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const problems = [];

const [major, minor] = process.versions.node.split(".").map(Number);
const nodeOk = (major === 22 && minor >= 12) || major === 24 || major >= 26;
if (!nodeOk) {
  const range = JSON.parse(readFileSync(new URL("package.json", root), "utf8")).engines.node;
  problems.push(`Node.js ${process.versions.node} is not supported. This project needs Node ${range}.`);
}

for (const file of ["vite/client.d.ts", "@types/node/package.json", "typescript/package.json"]) {
  if (!existsSync(new URL(`node_modules/${file}`, root))) {
    problems.push(`node_modules/${file} is missing: dependencies aren't installed.`);
  }
}

if (problems.length) {
  console.error(["Can't build yet:", ...problems.map((p) => `  - ${p}`), "Fix: from frontend/, run `npm ci` (it must finish without errors), then `npm run build`."].join("\n"));
  process.exit(1);
}
