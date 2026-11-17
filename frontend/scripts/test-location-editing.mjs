import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";

const temp = mkdtempSync(join(tmpdir(), "maia-location-editing-"));
const file = join(temp, "location-editing.cjs");
writeFileSync(
  file,
  ts.transpileModule(
    readFileSync("src/shared/lib/location-editing.ts", "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText,
);
const { LocationEditing } = createRequire(import.meta.url)(file);
after(() => rmSync(temp, { recursive: true, force: true }));
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));
const point = (id, latitude = 20.67) => ({
  id,
  latitude,
  longitude: -103.35,
  source: "google",
  expires_at: "2027-01-01",
  needs_confirmation: false,
});
function setup(values = {}, { automaticConfig = true } = {}) {
  let data = {
    kind: "house",
    private_address: "",
    state: "Jalisco",
    ...values,
  };
  let location = null;
  const changes = [],
    pending = [],
    requests = [];
  const context = () => ({
    data,
    location,
    states: ["Jalisco", "Yucatán"],
    signedIn: true,
  });
  const editor = new LocationEditing(context(), {
    delay: 0,
    request: (path, init) => {
      if (path === "/location/config" && automaticConfig)
        return Promise.resolve({ enabled: true });
      return new Promise((resolve, reject) =>
        requests.push({
          path,
          init,
          body: init?.body ? JSON.parse(init.body) : {},
          resolve,
          reject,
        }),
      );
    },
    onData: (value) => {
      data = value;
      changes.push(value);
    },
    onLocation: (value) => {
      location = value;
    },
    onPending: (value) => pending.push(value),
  });
  return {
    editor,
    requests,
    pending,
    changes,
    data: () => data,
    location: () => location,
    context,
  };
}

async function search(form, text) {
  form.editor.focus(true);
  form.editor.search(text);
  await tick();
  return form.requests.at(-1);
}

test("newer suggestions win even when an aborted transport still completes", async () => {
  const form = setup();
  form.editor.start();
  await tick();
  const older = await search(form, "Alcalde");
  const newer = await search(form, "Chopin");
  assert.equal(older.init.signal.aborted, true);
  newer.resolve({
    session: "new-session",
    suggestions: [{ id: "new", label: "Chopin" }],
  });
  await tick();
  older.resolve({
    session: "old-session",
    suggestions: [{ id: "old", label: "Alcalde" }],
  });
  await tick();
  assert.equal(form.editor.snapshot.items[0].id, "new");
  const choosing = form.editor.choose(form.editor.snapshot.items[0]);
  assert.equal(form.requests.at(-1).body.session, "new-session");
  form.requests.at(-1).resolve({
    fields: { private_address: "Chopin 1", state: "Jalisco" },
    location: point("new-point"),
  });
  await choosing;
  assert.equal(
    form.data().municipality,
    "",
    "Locality is never substituted for municipality",
  );
  assert.equal(form.data().location_ref, "new-point");
  assert.equal(form.data().location_confirmed, false);
  form.editor.dispose();
});

test("a late resolution cannot replace a newer pin or clear its pending operation", async () => {
  const form = setup();
  const choosing = form.editor.choose({ id: "chosen", label: "Chosen" });
  const oldResolve = form.requests.at(-1);
  const moving = form.editor.selectPoint(21, -104);
  const latestPoint = form.requests.at(-1);
  oldResolve.resolve({
    fields: { private_address: "Old address" },
    location: point("old"),
  });
  await choosing;
  assert.equal(form.editor.snapshot.busy, true);
  latestPoint.resolve({ location: point("latest", 21) });
  await moving;
  assert.equal(form.data().location_ref, "latest");
  assert.equal(form.location().latitude, 21);
  assert.equal(form.editor.snapshot.busy, false);
  form.editor.dispose();
});

test("a late failed drag cannot overwrite a successful newer drag or stop its pending state", async () => {
  const form = setup();
  const first = form.editor.selectPoint(20, -103);
  const old = form.requests.at(-1);
  const second = form.editor.selectPoint(21, -104);
  const latest = form.requests.at(-1);
  old.reject(new Error("Obsolete failure"));
  await first;
  assert.equal(form.editor.snapshot.failure, "");
  assert.equal(form.editor.snapshot.busy, true);
  latest.resolve({ location: point("latest", 21) });
  await second;
  assert.equal(form.data().location_ref, "latest");
  assert.equal(form.pending.at(-1), false);
  form.editor.dispose();
});

test("editing address/state cancels selection; municipality preserves a point pending confirmation", async () => {
  const form = setup();
  const selecting = form.editor.choose({ id: "old", label: "Old" });
  const old = form.requests.at(-1);
  form.editor.edit({ state: "Yucatán" });
  old.resolve({ fields: { state: "Jalisco" }, location: point("stale") });
  await selecting;
  assert.equal(form.data().state, "Yucatán");
  assert.equal(form.data().location_ref, null);
  const moving = form.editor.selectPoint(20, -103);
  form.requests.at(-1).resolve({ location: point("saved") });
  await moving;
  form.editor.edit({ municipality: "Municipio manual" });
  form.editor.edit({ neighborhood: "Colonia manual" });
  assert.equal(form.data().location_ref, "saved");
  assert.equal(form.location().id, "saved");
  assert.equal(form.data().location_confirmed, false);
  form.editor.dispose();
});

test("rural reference selection leaves address and neighborhood empty and keeps latest unrelated edits", async () => {
  const form = setup({
    kind: "ranch",
    location_mode: "reference",
    location_reference: "Camino rural",
  });
  const selecting = form.editor.choose({ id: "nearby", label: "Nearby" });
  form.editor.edit({ location_reference: "Entrada por el camino norte" });
  form.requests.at(-1).resolve({
    fields: {
      private_address: "Calle cercana 1",
      municipality: "Zapopan",
      neighborhood: "Colonia cercana",
      state: "Jalisco",
    },
    location: point("reference"),
  });
  await selecting;
  assert.equal(form.data().private_address, "");
  assert.equal(form.data().neighborhood, "");
  assert.equal(form.data().location_reference, "Entrada por el camino norte");
  assert.equal(form.data().municipality, "Zapopan");
  form.editor.dispose();
});

test("unmount discards pending successes/errors and point restoration, and releases pending state", async () => {
  const form = setup({ location_ref: "restore" }, { automaticConfig: false });
  form.editor.start();
  const config = form.requests.find(
    (request) => request.path === "/location/config",
  );
  const restore = form.requests.find((request) =>
    request.path.includes("/points/"),
  );
  const moving = form.editor.selectPoint(21, -104);
  const pending = form.requests.at(-1);
  form.editor.dispose();
  config.resolve({ enabled: true });
  restore.resolve({ location: point("restore") });
  pending.reject(new Error("Late failure"));
  await moving;
  await tick();
  assert.equal(form.location(), null);
  assert.equal(form.changes.length, 0);
  assert.equal(form.editor.snapshot.failure, "");
  assert.equal(form.pending.at(-1), false);
});

test("late configuration does not cancel a pin request and a changed login invalidates it", async () => {
  const form = setup({}, { automaticConfig: false });
  form.editor.start();
  const config = form.requests[0];
  const moving = form.editor.selectPoint(21, -104);
  const pending = form.requests.at(-1);
  config.resolve({ enabled: true });
  await tick();
  assert.equal(form.editor.snapshot.busy, true);
  form.editor.update({ ...form.context(), signedIn: false });
  pending.resolve({ location: point("after-logout") });
  await moving;
  assert.equal(form.location(), null);
  assert.equal(form.data().location_ref, undefined);
  form.editor.dispose();
});

test("restored private points cannot overwrite a new selection after editing", async () => {
  const form = setup({ location_ref: "old-ref" });
  form.editor.start();
  const restore = form.requests.find((request) =>
    request.path.includes("/points/"),
  );
  form.editor.edit({ state: "Yucatán" });
  restore.resolve({ location: point("old-ref") });
  await tick();
  assert.equal(form.location(), null);
  assert.equal(form.data().location_ref, null);
  form.editor.dispose();
});

test("an obsolete selection cannot consume a newer search session", async () => {
  const form = setup();
  form.editor.start();
  await tick();
  const originalSearch = await search(form, "Primera calle");
  originalSearch.resolve({
    session: "session-a",
    suggestions: [{ id: "a", label: "A" }],
  });
  await tick();
  const oldChoosing = form.editor.choose({ id: "a", label: "A" });
  const oldResolve = form.requests.at(-1);
  const newerSearch = await search(form, "Segunda calle");
  newerSearch.resolve({
    session: "session-b",
    suggestions: [{ id: "b", label: "B" }],
  });
  await tick();
  oldResolve.resolve({
    fields: { private_address: "Old" },
    location: point("old"),
  });
  await oldChoosing;
  const choosing = form.editor.choose({ id: "b", label: "B" });
  const latest = form.requests.at(-1);
  assert.equal(latest.body.session, "session-b");
  latest.resolve({
    fields: { private_address: "Nueva calle" },
    location: point("new"),
  });
  await choosing;
  assert.equal(form.data().location_ref, "new");
  form.editor.dispose();
});

test("a missing private point is looked up once per edit rather than on every field rerender", async () => {
  const form = setup({ location_ref: "missing" });
  form.editor.start();
  const restore = form.requests.find((request) =>
    request.path.includes("/points/"),
  );
  restore.reject(new Error("Unavailable point"));
  await tick();
  form.editor.edit({ subdivision: "Coto" });
  form.editor.update(form.context());
  assert.equal(
    form.requests.filter((request) => request.path.includes("/points/")).length,
    1,
  );
  assert.equal(
    form.editor.snapshot.note,
    "Vuelve a señalar el punto para confirmar esta ubicación.",
  );
  form.editor.dispose();
});
