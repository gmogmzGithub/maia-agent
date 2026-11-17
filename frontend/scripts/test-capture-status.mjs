import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";
const temp = mkdtempSync(join(tmpdir(), "maia-capture-status-"));
const file = join(temp, "status.cjs");
writeFileSync(
  file,
  ts.transpileModule(readFileSync("src/crm/lib/capture-status.ts", "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
);
const { captureTabs, captureState, captureTabForStatus, capturesInTab } =
  createRequire(import.meta.url)(file);
after(() => rmSync(temp, { recursive: true, force: true }));
const rows = [
  "published",
  "approved",
  "submitted",
  "accepted",
  "withdrawn",
  "expired",
  "rejected",
].map((status, id) => ({ id: String(id), status }));
test("tab counts come from captures, keep review separate and closed states accessible in All", () => {
  assert.deepEqual(
    captureTabs.map((tab) => capturesInTab(rows, tab.id).length),
    [1, 2, 1, 7],
  );
  assert.deepEqual(
    capturesInTab(rows, "process").map((row) => row.status),
    ["approved", "accepted"],
  );
  assert.deepEqual(capturesInTab(rows, "all"), rows); // Preserve server ordering.
});
test("review approval never suggests that the property is already published or can skip acceptance", () => {
  const waiting = captureState("approved");
  const ready = captureState("accepted");
  assert.match(waiting.label, /aceptación/);
  assert.match(waiting.next, /propietario.*aceptar.*exclusividad/);
  assert.notEqual(waiting.tone, ready.tone);
  assert.equal(ready.label, "Lista para publicar");
  assert.equal(captureState("published").label, "Publicada");
});
test("deep links route to the corresponding group; unknown states never look published", () => {
  assert.equal(captureTabForStatus("submitted"), "review");
  assert.equal(captureTabForStatus("approved"), "process");
  assert.equal(captureTabForStatus("accepted"), "process");
  assert.equal(captureTabForStatus("published"), "published");
  assert.equal(captureTabForStatus("expired"), "all");
  assert.equal(captureState("unexpected").tone, "closed");
});
