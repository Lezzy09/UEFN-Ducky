import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

// Vitest 5 on Windows loads a second copy of its runtime when the drive
// letter in the CLI path disagrees with Vite's module ids (`c:\` vs `C:\`).
// Git Bash starts with a lowercase drive, and every suite then dies in
// beforeEach. ponytail: force the drive letter uppercase until Vitest ships
// a case-insensitive resolver (vitest-dev/vitest#10843, closed unmerged).
function upperDrive(p) {
  return process.platform === "win32" ? p.replace(/^([a-z]):/, (_, d) => `${d.toUpperCase()}:`) : p;
}

const cwd = upperDrive(fileURLToPath(new URL("..", import.meta.url)));
const bin = upperDrive(fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url)));
const child = spawn(process.execPath, [bin, "run", ...process.argv.slice(2)], {
  cwd,
  stdio: "inherit",
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
