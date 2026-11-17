import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const output = mkdtempSync(join(tmpdir(), "maia-conversation-tests-"));
try {
  const compiled = spawnSync(process.execPath, [
    "node_modules/typescript/bin/tsc", "tests/conversation-session.test.ts",
    "--outDir", output, "--rootDir", ".", "--module", "commonjs",
    "--target", "ES2020", "--esModuleInterop", "--skipLibCheck", "--strict",
  ], { stdio: "inherit" });
  if (compiled.status !== 0) process.exitCode = compiled.status ?? 1;
  else {
    const tested = spawnSync(process.execPath, ["--test", join(output, "tests/conversation-session.test.js")], { stdio: "inherit" });
    process.exitCode = tested.status ?? 1;
  }
} finally {
  rmSync(output, { recursive: true, force: true });
}
