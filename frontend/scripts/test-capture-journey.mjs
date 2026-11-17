import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";
const temp = mkdtempSync(join(tmpdir(), "maia-capture-journey-"));
for (const [source, name] of [
  ["src/main-website/lib/owner-draft.ts", "owner-draft.js"],
  ["src/main-website/lib/owner-capture-journey.ts", "owner-capture-journey.js"],
  ["src/crm/lib/capture-review-session.ts", "capture-review-session.js"],
])
  writeFileSync(
    join(temp, name),
    ts.transpileModule(readFileSync(source, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  );
const require = createRequire(import.meta.url);
const { OwnerCaptureJourney } = require(join(temp, "owner-capture-journey.js"));
const { CaptureReviewSession } = require(
  join(temp, "capture-review-session.js"),
);
after(() => rmSync(temp, { recursive: true, force: true }));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const row = (id = "a", revision = 1, status = "draft") => ({
  id,
  revision,
  status,
  data: { title: id },
  assets: [],
});
const owner = { email: "owner@example.com", verified: true };
function journeyHarness(request = async () => {}) {
  const changes = [],
    rows = [],
    feedback = [],
    accounts = [];
  const journey = new OwnerCaptureJourney({
    request,
    session: async () => {},
    changed: (value) => changes.push(value),
    rows: (value) => rows.push(value),
    feedback: (value) => feedback.push(value),
    needsAccount: () => accounts.push(true),
    blocked: () => false,
  });
  return { journey, changes, rows, feedback, accounts };
}
const context = (
  account = owner,
  capture = null,
  data = { title: "latest" },
  draftId = "a",
) => ({ owner: account, capture, data, draftId });
test("registration and verification resume the current draft once with fresh data and revision", async () => {
  const writes = [];
  const h = journeyHarness(async (_path, init) => {
    writes.push(JSON.parse(init.body));
    return row("a", 8);
  });
  h.journey.update(context(null, null, { title: "before registration" }));
  h.journey.requireAccount(async () => {
    await h.journey.persist();
  });
  assert.equal(h.accounts.length, 1);
  h.journey.update(context({ ...owner, verified: false }));
  await h.journey.resumePending();
  assert.equal(writes.length, 0);
  h.journey.update(
    context(owner, row("a", 7), { title: "after verification" }),
  );
  await h.journey.resumePending();
  await h.journey.resumePending();
  assert.deepEqual(writes, [
    { id: "a", revision: 7, data: { title: "after verification" } },
  ]);
  assert.equal(h.changes[0].revision, 8);
});
test("changing account or draft discards deferred anonymous work", async () => {
  for (const change of ["account", "draft"]) {
    const h = journeyHarness();
    let executed = 0;
    h.journey.update(context(null));
    h.journey.requireAccount(async () => {
      executed++;
    });
    h.journey.update(context({ ...owner, verified: false }));
    h.journey.update(
      change === "account"
        ? context({ ...owner, email: "other@example.com" })
        : context(owner, null, {}, "b"),
    );
    await h.journey.resumePending();
    assert.equal(executed, 0);
  }
});
test("a late persisted draft cannot replace another account's current capture", async () => {
  const response = deferred();
  const h = journeyHarness(() => response.promise);
  h.journey.update(context(owner, row()));
  const saving = h.journey.persist();
  h.journey.update(
    context({ ...owner, email: "other@example.com" }, row("b"), {}, "b"),
  );
  response.resolve(row("a", 2));
  await assert.rejects(saving, /cuenta o la solicitud cambió/);
  assert.equal(h.changes.length, 0);
});
test("list reads survive draft navigation but never cross account changes", async () => {
  for (const accountChanged of [false, true]) {
    const response = deferred();
    const h = journeyHarness(() => response.promise);
    h.journey.update(context());
    const reading = h.journey.loadRows();
    h.journey.update(
      context(
        accountChanged ? { ...owner, email: "other@example.com" } : owner,
        row("b"),
        {},
        "b",
      ),
    );
    response.resolve({ captures: [row()] });
    await reading;
    assert.equal(h.rows.length, accountChanged ? 0 : 1);
  }
});
test("a late mail deep link cannot reopen a draft after navigation", async () => {
  const response = deferred();
  const h = journeyHarness(() => response.promise);
  h.journey.update(context());
  const opening = h.journey.openRequested("a");
  h.journey.cancelOpen();
  response.resolve(row());
  assert.equal(await opening, null);
});
test("bootstrap authorizes a cached draft and ignores an older disposed mount", async () => {
  let authorize = 0;
  const h = journeyHarness(async (path) => {
    if (path === "/capture/catalog") return {};
    if (path === "/capture/account") return { account: owner };
    authorize++;
    return row("a", 4);
  });
  const saved = JSON.stringify({
    id: "a",
    ownerEmail: owner.email,
    data: { title: "local" },
    capture: row("a", 3),
  });
  const result = await h.journey.bootstrap(saved);
  assert.equal(authorize, 1);
  assert.equal(result.draft.data.title, "local");
  const stale = h.journey.bootstrap(saved);
  h.journey.stop();
  h.journey.resume();
  assert.equal(await stale, null);
});
test("the owner operation gate suppresses simultaneous submissions and releases after failure", async () => {
  const h = journeyHarness();
  const pause = deferred();
  let calls = 0;
  h.journey.update(context());
  const first = h.journey.run(async () => {
    calls++;
    await pause.promise;
  });
  await h.journey.run(async () => {
    calls++;
  });
  pause.resolve();
  await first;
  await h.journey.run(async () => {
    calls++;
    throw new Error("failure");
  });
  assert.equal(calls, 2);
  assert.equal(h.feedback.at(-1).busy, false);
  assert.ok(h.feedback.some((value) => value.error?.message === "failure"));
});
test("CRM keeps a confirmed approval when its subsequent list read fails", async () => {
  let writes = 0;
  const review = new CaptureReviewSession({
    request: async (_path, init) => {
      if (init?.method === "POST") {
        writes++;
        return row("a", 2, "approved");
      }
      throw new Error("offline");
    },
    now: () => "12:00",
  });
  review.select(row("a", 1, "submitted"));
  await review.act("approve");
  assert.equal(writes, 1);
  assert.equal(review.snapshot().selected.status, "approved");
  assert.equal(review.snapshot().rows[0].revision, 2);
  assert.equal(review.snapshot().error, null);
  assert.match(
    review.snapshot().notice,
    /Revisión aprobada.*lista no pudo actualizarse/,
  );
  assert.equal(review.snapshot().busy, false);
});
test("CRM cannot replace a newly selected request with an older write response", async () => {
  const response = deferred();
  const review = new CaptureReviewSession({
    request: async (_path, init) =>
      init?.method === "POST"
        ? response.promise
        : { captures: [row("a", 2), row("b")] },
    now: () => "12:00",
  });
  review.select(row());
  const writing = review.act("approve");
  review.select(row("b"));
  response.resolve(row("a", 2, "approved"));
  await writing;
  assert.equal(review.snapshot().selected.id, "b");
  assert.equal(review.snapshot().notice, "");
});
test("CRM serializes writes and preserves structured rejection for the caller", async () => {
  const response = deferred();
  let writes = 0;
  const failure = Object.assign(new Error("outside zone"), {
    issues: [
      {
        field: "outside_area_approved",
        code: "outside_area_approval_required",
      },
    ],
  });
  const review = new CaptureReviewSession({
    request: async () => {
      writes++;
      return response.promise;
    },
    now: () => "12:00",
  });
  review.select(row());
  const first = review.act("approve");
  await review.act("approve");
  response.reject(failure);
  await first;
  assert.equal(writes, 1);
  assert.equal(review.snapshot().error, failure);
  assert.equal(review.snapshot().selected.revision, 1);
});
test("CRM ignores an old selection's refresh", async () => {
  const response = deferred();
  const review = new CaptureReviewSession({
    request: async (path) =>
      path === "/crm/captures" ? { captures: [row()] } : response.promise,
    now: () => "12:00",
  });
  review.select(row());
  const refreshing = review.refresh();
  await Promise.resolve();
  await Promise.resolve();
  review.select(row("b"));
  response.resolve(row("a", 2));
  await refreshing;
  assert.equal(review.snapshot().selected.id, "b");
});

test("CRM list reconciliation cannot downgrade a confirmed revision", async () => {
  const review = new CaptureReviewSession({
    request: async (_path, init) => init?.method === "POST" ? row("a", 5, "published") : { captures: [row("a", 4, "accepted")] },
    now: () => "12:00",
  });
  review.select(row("a", 4, "accepted"));
  await review.act("publish");
  assert.equal(review.snapshot().selected.status, "published");
  assert.equal(review.snapshot().rows[0].status, "published");
  assert.equal(review.snapshot().rows[0].revision, 5);
});

test("persist rejects unverified owners without sending a write", async () => {
  let requests = 0;
  const h = journeyHarness(async () => { requests++; });
  h.journey.update(context({ ...owner, verified: false }));
  await assert.rejects(h.journey.persist(), /Verifica tu email/);
  assert.equal(requests, 0);
});
