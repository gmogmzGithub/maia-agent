import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";

const temp = mkdtempSync(join(tmpdir(), "maia-easybroker-review-"));
writeFileSync(
  join(temp, "session.cjs"),
  ts.transpileModule(
    readFileSync("src/crm/lib/easybroker-review-session.ts", "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText,
);
const { EasyBrokerReviewSession } = createRequire(import.meta.url)(
  join(temp, "session.cjs"),
);
after(() => rmSync(temp, { recursive: true, force: true }));
const root = "/crm/easybroker";
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const row = (id = "a", revision = 1) => ({
  id,
  revision,
  links: [],
  facts: {},
  geography: {},
});
const page = (...items) => ({ items, count: items.length, next_offset: null });
const account = (revision = 1) => ({ id: "account", revision, last_run: null });
function harness(handle = async () => undefined) {
  const calls = [],
    changed = [];
  let requests = 0;
  const review = new EasyBrokerReviewSession({
    request: async (path, init) => {
      calls.push({ path, init });
      const custom = await handle(path, init);
      if (custom !== undefined) return custom;
      if (path === `${root}/connections`)
        return { items: [account()], admin: true, public_enabled: false };
      if (path.startsWith(`${root}/imports?`)) return page(row());
      if (path === "/crm/advisors" || path === "/crm/properties") return [];
      if (path.startsWith(`${root}/imports/`))
        return row(path.split("/").at(-1));
      throw new Error(`Unexpected request: ${path}`);
    },
    requestId: () => `request-${++requests}`,
    changed: () => changed.push(true),
  });
  return { review, calls, changed };
}

test("a late previous page cannot overwrite the active page", async () => {
  const old = deferred(),
    current = deferred();
  const { review } = harness(async (path) => {
    if (path.endsWith("offset=0")) return old.promise;
    if (path.endsWith("offset=50")) return current.promise;
  });
  const loading = review.refresh();
  const moving = review.page(50);
  current.resolve(page(row("current")));
  await moving;
  old.resolve(page(row("old")));
  await loading;
  assert.equal(review.snapshot().offset, 50);
  assert.equal(review.snapshot().listings.items[0].id, "current");
});

test("closing or replacing a selection discards late detail", async () => {
  for (const target of [null, "b"]) {
    const pending = deferred();
    const { review } = harness(async (path) =>
      path === `${root}/imports/a` ? pending.promise : undefined,
    );
    const opening = review.select("a");
    await review.select(target);
    pending.resolve(row("a"));
    await opening;
    assert.equal(review.snapshot().selected?.id || null, target);
  }
});

test("confirmed import writes survive refresh failures without prompting another write", async () => {
  let saved = false;
  const { review, calls, changed } = harness(async (_path, init) => {
    if (init?.method === "POST") {
      saved = true;
      return row("a", 2);
    }
    if (saved) throw new Error("refresh unavailable");
  });
  await review.load();
  await review.select("a");
  assert.equal(
    await review.mutate("/imports/a/actions", {
      action: "approve",
      revision: 1,
    }),
    true,
  );
  const state = review.snapshot();
  assert.equal(state.busy, false);
  assert.equal(state.error, null);
  assert.equal(state.listings.items[0].revision, 2);
  assert.match(state.notice, /^Cambio guardado\..*Actualizar lista/);
  assert.equal(calls.filter((call) => call.init?.method === "POST").length, 1);
  assert.equal(changed.length, 1);
});

test("double submission makes one request and stale reconciliation cannot downgrade a confirmed revision", async () => {
  const write = deferred();
  const { review, calls } = harness(async (_path, init) =>
    init?.method === "POST" ? write.promise : undefined,
  );
  await review.load();
  const saving = review.mutate("/imports/a/actions", {
    action: "approve",
    revision: 1,
  });
  assert.equal(
    await review.mutate("/imports/a/actions", {
      action: "approve",
      revision: 1,
    }),
    false,
  );
  write.resolve(row("a", 3));
  await saving;
  assert.equal(review.snapshot().listings.items[0].revision, 3);
  const writes = calls.filter((call) => call.init?.method === "POST");
  assert.equal(writes.length, 1);
  assert.equal(JSON.parse(writes[0].init.body).request_id, "request-1");
});

test("connection changes remain confirmed when an older list is returned", async () => {
  const { review } = harness(async (_path, init) =>
    init?.method === "POST" ? account(4) : undefined,
  );
  await review.load();
  await review.mutate("/connections/account/actions", {
    action: "configure",
    revision: 1,
  });
  assert.equal(review.snapshot().accounts.items[0].revision, 4);
});

test("a poll started before a write cannot publish a late error", async () => {
  const poll = deferred();
  let delaying = false,
    written = false;
  const { review } = harness(async (path, init) => {
    if (init?.method === "POST") {
      written = true;
      return row("a", 2);
    }
    if (delaying && !written && path.includes("imports?")) return poll.promise;
  });
  await review.load();
  delaying = true;
  const pending = review.refresh();
  await review.mutate("/imports/a/actions", { action: "approve", revision: 1 });
  poll.reject(new Error("old poll failed"));
  await pending;
  assert.equal(review.snapshot().error, null);
  assert.equal(review.snapshot().notice, "Cambio guardado.");
});

test("stopping discards late detail and side effects of a finished write", async () => {
  const response = deferred();
  const { review, changed } = harness(async (_path, init) =>
    init?.method === "POST" ? response.promise : undefined,
  );
  await review.load();
  const saving = review.mutate("/imports/a/actions", {
    action: "approve",
    revision: 1,
  });
  review.stop();
  response.resolve(row("a", 2));
  assert.equal(await saving, true);
  assert.equal(changed.length, 0);
  assert.equal(review.snapshot().listings.items[0].revision, 1);
});

test("opening an older detail cannot override a newer known revision", async () => {
  const { review } = harness(async (path) =>
    path.includes("imports?") ? page(row("a", 4)) : undefined,
  );
  await review.load();
  await review.select("a");
  assert.equal(review.snapshot().selected, null);
  assert.match(review.snapshot().error.message, /versión vigente/);
});
