// Starts the FastAPI backend and the Vite dev server together so the Enterprise
// UI can reach /api during development without a second terminal. Zero external
// dependencies (uses only Node built-ins) so it works with the committed
// node_modules. Cross-platform: resolves a project venv first, then falls back
// to `py` (Windows) or `python3`/`python`.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, "..");
const repoRoot = resolve(webRoot, "..");

function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venvPython =
    process.platform === "win32"
      ? resolve(repoRoot, ".venv", "Scripts", "python.exe")
      : resolve(repoRoot, ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  return process.platform === "win32" ? "py" : "python3";
}

const python = resolvePython();
const viteEntry = resolve(webRoot, "node_modules", "vite", "bin", "vite.js");

const children = [];
let shuttingDown = false;

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      try {
        child.kill();
      } catch {
        /* already gone */
      }
    }
  }
  process.exit(code);
}

function launch(label, command, args, opts) {
  console.log(`[dev:full] starting ${label}: ${command} ${args.join(" ")}`);
  const child = spawn(command, args, { stdio: "inherit", ...opts });
  child.on("error", (err) => {
    console.error(`[dev:full] failed to start ${label}: ${err.message}`);
    shutdown(1);
  });
  child.on("exit", (exitCode) => {
    console.log(`[dev:full] ${label} exited (code ${exitCode ?? "null"}); stopping the rest.`);
    shutdown(exitCode ?? 0);
  });
  children.push(child);
  return child;
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

launch("api", python, ["-m", "cobol_error_scanner.api.server"], { cwd: repoRoot });
launch("web", process.execPath, [viteEntry], { cwd: webRoot });
