import assert from "node:assert/strict";
import { test } from "node:test";
import type { Conversation } from "../src/shared/lib/api";
import { ConversationSession, type ConversationIO } from "../src/main-website/conversation/session";

function conversation(id = "one", processing = false): Conversation {
  return { id, processing, criteria: { verified_only: false }, messages: [], contact_registered: false,
    automation_paused: false, human_requested: false, has_interest: false,
    visits_processing: false, structured_reply: true };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const tick = () => new Promise<void>((done) => setImmediate(done));

function setup(handler: (path: string, init?: RequestInit) => Promise<unknown>, saved: string | null = null) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const timers = new Map<ReturnType<typeof setTimeout>, { callback: () => void; delay: number }>();
  let identity = 0;
  const io: ConversationIO = {
    request: async <T>(path: string, init?: RequestInit) => {
      calls.push({ path, init });
      return await handler(path, init) as T;
    },
    session: async () => ({ ai_configured: true }),
    saved: { get: () => saved, set: (id) => { saved = id; }, clear: () => { saved = null; } },
    id: () => `message-${++identity}`,
    schedule: (callback, delay) => {
      const timer = setTimeout(() => {}, 60000);
      timer.unref();
      timers.set(timer, { callback, delay });
      return timer;
    },
    cancel: (timer) => { clearTimeout(timer); timers.delete(timer); },
  };
  return { session: new ConversationSession(io), calls, timers, io };
}

test("restore before recording property interest; preserve draft and suppress simultaneous clicks", async () => {
  const write = deferred<Conversation>();
  const { session, calls } = setup(async (path, init) => init?.method === "POST" ? write.promise : conversation(), "one");
  let consumed = 0;
  session.setText("Un borrador que quiero conservar");
  const starting = session.start("3", () => { consumed++; });
  await tick();
  await session.send("Otro clic", false, 4);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, "/conversations/one");
  assert.equal(calls[1].path, "/conversations/one/messages");
  assert.equal(JSON.parse(String(calls[1].init?.body)).property_id, 3);
  assert.equal(consumed, 1);
  write.resolve(conversation());
  await starting;
  assert.equal(session.snapshot().text, "Un borrador que quiero conservar");
  session.stop();
});

test("retry reuses message identity and does not create a second conversation", async () => {
  let attempts = 0;
  const { session, calls } = setup(async (path, init) => {
    if (path.endsWith("/messages") && ++attempts === 1) throw new Error("Connection lost");
    return conversation();
  });
  await session.start(null, () => {});
  session.setText("Hola");
  await session.send("Hola");
  assert.equal(session.snapshot().canRetry, true);
  session.retry();
  await tick();
  const posts = calls.filter((call) => call.path.endsWith("/messages"));
  assert.equal(posts.length, 2);
  assert.equal(posts[0].init?.body, posts[1].init?.body);
  assert.equal(calls.filter((call) => call.path === "/conversations").length, 1);
  assert.equal(session.snapshot().text, "");
  assert.equal(session.snapshot().canRetry, false);
  session.stop();
});

test("late polling cannot restore a discarded conversation", async () => {
  const late = deferred<Conversation>();
  let reads = 0;
  const { session } = setup(async () => ++reads === 1 ? conversation() : late.promise, "one");
  await session.start(null, () => {});
  const poll = session.refresh();
  session.newSearch();
  late.resolve(conversation("one", true));
  await poll;
  assert.equal(session.snapshot().conversation, null);
  assert.equal(session.snapshot().canRefresh, false);
  session.stop();
});

test("an earlier poll cannot replace a newer confirmed form result", async () => {
  const late = deferred<Conversation>();
  let reads = 0;
  const { session } = setup(async () => ++reads === 1 ? conversation() : late.promise, "one");
  await session.start(null, () => {});
  const poll = session.refresh();
  session.update({ ...conversation(), contact_registered: true });
  late.resolve(conversation());
  await poll;
  assert.equal(session.snapshot().conversation?.contact_registered, true);
  session.stop();
});

test("unmount discards late results and cancels polling and waiting timers", async () => {
  const late = deferred<Conversation>();
  let reads = 0;
  const { session, timers } = setup(async () => ++reads === 1 ? conversation("one", true) : late.promise, "one");
  await session.start(null, () => {});
  assert.ok([...timers.values()].some((timer) => timer.delay === 15000));
  session.stop();
  const before = session.snapshot();
  late.resolve(conversation("one", false));
  await tick();
  assert.equal(session.snapshot(), before);
  assert.equal(timers.size, 0);
});

test("poll only schedules another read while work remains", async () => {
  let reads = 0;
  const { session, timers, io } = setup(async () => conversation("one", ++reads < 3), "one");
  await session.start(null, () => {});
  await tick();
  const next = [...timers.entries()].find(([, timer]) => timer.delay === 1200);
  assert.ok(next);
  io.cancel(next[0]);
  next[1].callback();
  await tick();
  assert.equal(session.snapshot().conversation?.processing, false);
  assert.equal(timers.size, 0);
  session.stop();
});
