import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";

const temp = mkdtempSync(join(tmpdir(), "maia-owner-draft-"));
const file = join(temp, "draft.cjs");
writeFileSync(
  file,
  ts.transpileModule(
    readFileSync("src/main-website/lib/owner-draft.ts", "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText,
);
const { restoreOwnerDraft } = createRequire(import.meta.url)(file);
after(() => rmSync(temp, { recursive: true, force: true }));
const owner = { email: "owner@example.com", verified: true };
const capture = {
  id: "request-a",
  revision: 3,
  status: "draft",
  location: { latitude: 20, longitude: -103 },
};
const draft = {
  id: capture.id,
  data: { title: "Local edits" },
  capture,
  ownerEmail: owner.email,
};

test("resume saved local edits only after authorizing the capture with the actual account", async () => {
  const calls = [];
  const restored = await restoreOwnerDraft(
    JSON.stringify(draft),
    owner,
    async (id) => {
      calls.push(id);
      return capture;
    },
  );
  assert.deepEqual(calls, ["request-a"]);
  assert.equal(restored.data.title, "Local edits");
  assert.equal(restored.capture.revision, 3);
  assert.equal(restored.capture.location, undefined);
});
test("another account cannot restore cached private content", async () => {
  let called = false;
  const restored = await restoreOwnerDraft(
    JSON.stringify(draft),
    { email: "other@example.com", verified: true },
    async () => {
      called = true;
      return capture;
    },
  );
  assert.equal(restored, null);
  assert.equal(called, false);
});
test("legacy cached captures still require a successful authorized read", async () => {
  assert.equal(
    await restoreOwnerDraft(
      JSON.stringify({ ...draft, ownerEmail: undefined }),
      owner,
      async () => {
        throw new Error("404");
      },
    ),
    null,
  );
});
test("logged-out or unverified accounts cannot restore an existing capture", async () => {
  for (const account of [null, { ...owner, verified: false }])
    assert.equal(
      await restoreOwnerDraft(
        JSON.stringify({ ...draft, ownerEmail: undefined }),
        account,
        async () => capture,
      ),
      null,
    );
});
test("an anonymous unfinished form can continue during first registration", async () => {
  const guest = {
    id: "new-request",
    data: { municipality: "Zapopan" },
    capture: null,
    ownerEmail: null,
  };
  for (const account of [null, owner, { ...owner, verified: false }])
    assert.equal(
      (
        await restoreOwnerDraft(JSON.stringify(guest), account, async () => {
          throw new Error("Unexpected");
        })
      ).data.municipality,
      "Zapopan",
    );
});
test("malformed local records are discarded safely", async () => {
  for (const value of ["invalid", "null", "{}", "[]"])
    assert.equal(
      await restoreOwnerDraft(value, owner, async () => capture),
      null,
    );
});


test("restore reconciles uploaded photos from the server without overwriting local fields or revision", async () => {
  const restored = await restoreOwnerDraft(
    JSON.stringify({ ...draft, capture: { ...capture, assets: [] } }),
    owner,
    async () => ({ ...capture, revision: 9, assets: [{ id: "accepted-upload" }] }),
  );
  assert.deepEqual(restored.capture.assets, [{ id: "accepted-upload" }]);
  assert.equal(restored.capture.revision, 3);
  assert.equal(restored.data.title, "Local edits");
});
