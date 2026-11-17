import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";

const temp = mkdtempSync(join(tmpdir(), "maia-uploads-"));
const file = join(temp, "queue.cjs");
writeFileSync(
  file,
  ts.transpileModule(
    readFileSync("src/main-website/lib/capture-upload-queue.ts", "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText,
);
const { CaptureUploadQueue, DEFAULT_UPLOAD_LIMITS } = createRequire(
  import.meta.url,
)(file);
after(() => rmSync(temp, { recursive: true, force: true }));
const photo = (name = "foto.jpg") =>
  new File(["image"], name, { type: "image/jpeg" });
const asset = (id, kind = "photo") => ({
  id,
  request_id: id,
  kind,
  url: "/private/" + id,
  content_type: "image/webp",
  size: 10,
});
function harness(queue, overrides = {}) {
  let current = { id: "capture-a", revision: 0, assets: [] };
  const calls = [];
  const adapter = {
    prepare: async () => current,
    upload: async (_id, item, uploading) => {
      uploading();
      calls.push(item.requestId);
      current = {
        ...current,
        revision: current.revision + 1,
        assets: [...current.assets, asset(item.requestId, item.kind)],
      };
      return current;
    },
    refresh: async () => current,
    changed: () => {},
    ...overrides,
  };
  queue.sync([], DEFAULT_UPLOAD_LIMITS);
  return {
    adapter,
    calls,
    setCapture: (value) => {
      current = value;
    },
  };
}

test("reserves only available photo slots, includes queued and failed items, keeps plans separate", async () => {
  const queue = new CaptureUploadQueue();
  const { adapter } = harness(queue, {
    upload: async () => {
      throw new Error("network");
    },
  });
  const existing = Array.from({ length: 18 }, (_, i) => asset(String(i)));
  queue.sync(existing, DEFAULT_UPLOAD_LIMITS);
  assert.equal(
    queue.enqueue([photo("a.jpg"), photo("b.jpg"), photo("c.jpg")], "photo")
      .length,
    1,
  );
  adapter.prepare = async () => ({ id: "capture-a", assets: existing });
  adapter.refresh = adapter.prepare;
  await queue.run(adapter);
  assert.equal(queue.enqueue([photo("d.jpg")], "photo").length, 1);
  assert.equal(
    queue.enqueue(
      [new File(["pdf"], "plano.pdf", { type: "application/pdf" })],
      "plan",
    ).length,
    0,
  );
});

test("one runner handles additions during upload, continues after failure, retry uses original request ID", async () => {
  const queue = new CaptureUploadQueue();
  const { adapter, calls } = harness(queue);
  const upload = adapter.upload;
  let release;
  const pause = new Promise((resolve) => {
    release = resolve;
  });
  let first = true;
  adapter.upload = async (...args) => {
    if (first) {
      first = false;
      await pause;
      throw new Error("one failure");
    }
    return upload(...args);
  };
  queue.enqueue([photo("a.jpg")], "photo");
  const originalId = queue.getSnapshot().items[0].requestId;
  const running = queue.run(adapter);
  await Promise.resolve();
  queue.enqueue([photo("b.jpg")], "photo");
  await queue.run(adapter); // Must not start a competing worker.
  release();
  await running;
  assert.deepEqual(
    queue.getSnapshot().items.map((item) => item.status),
    ["failed", "uploaded"],
  );
  queue.retry(originalId);
  await queue.run(adapter);
  assert.equal(calls.filter((id) => id === originalId).length, 1);
  assert.ok(
    queue
      .getSnapshot()
      .items.every((item) => item.status === "uploaded" && item.file === null),
  );
});

test("lost success response reconciles request ID and never sends the same photo twice", async () => {
  const queue = new CaptureUploadQueue();
  const { adapter, calls } = harness(queue);
  const upload = adapter.upload;
  adapter.upload = async (...args) => {
    await upload(...args);
    throw new Error("response lost");
  };
  queue.enqueue([photo()], "photo");
  await queue.run(adapter);
  const item = queue.getSnapshot().items[0];
  assert.equal(item.status, "uploaded");
  assert.equal(item.assetId, item.requestId);
  queue.retry(item.requestId);
  await queue.run(adapter);
  assert.equal(calls.length, 1);
});

test("retry reconciles before sending if the first reconciliation also failed", async () => {
  const queue = new CaptureUploadQueue();
  const { adapter, calls } = harness(queue);
  const upload = adapter.upload;
  const refresh = adapter.refresh;
  adapter.upload = async (...args) => {
    await upload(...args);
    throw new Error("response lost");
  };
  adapter.refresh = async () => {
    throw new Error("offline");
  };
  queue.enqueue([photo()], "photo");
  await queue.run(adapter);
  const item = queue.getSnapshot().items[0];
  assert.equal(item.status, "failed");
  adapter.refresh = refresh;
  queue.retry(item.requestId);
  await queue.run(adapter);
  assert.equal(queue.getSnapshot().items[0].status, "uploaded");
  assert.equal(calls.length, 1);
});

test("rejects PDF as photo without consuming a slot and accepts HEIC without browser MIME", () => {
  const queue = new CaptureUploadQueue();
  const rejected = queue.enqueue(
    [
      new File(["pdf"], "plan.pdf", { type: "application/pdf" }),
      new File(["heic"], "iPhone.HEIC"),
    ],
    "photo",
  );
  assert.equal(rejected.length, 1);
  assert.equal(queue.getSnapshot().items[0].name, "iPhone.HEIC");
});

test("removing a waiting file releases a slot; disposal stops subsequent uploads", async () => {
  const queue = new CaptureUploadQueue();
  const { adapter, calls } = harness(queue);
  queue.enqueue([photo("a.jpg"), photo("b.jpg")], "photo");
  queue.remove(queue.getSnapshot().items[0].requestId);
  assert.equal(queue.getSnapshot().items.length, 1);
  const prepare = adapter.prepare;
  adapter.prepare = async () => {
    queue.dispose();
    return prepare();
  };
  await queue.run(adapter);
  assert.equal(calls.length, 0);
});
