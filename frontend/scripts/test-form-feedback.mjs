import assert from "node:assert/strict";
import { test, after } from "node:test";
import { JSDOM } from "jsdom";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";
const dir = mkdtempSync(join(tmpdir(), "maia-feedback-"));
for (const name of ["form-feedback", "api-errors"])
  writeFileSync(
    join(dir, name + ".cjs"),
    ts.transpileModule(readFileSync("src/shared/lib/" + name + ".ts", "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  );
const require = createRequire(import.meta.url);
const { FormFeedback } = require(join(dir, "form-feedback.cjs"));
const { ApiError, responseError } = require(join(dir, "api-errors.cjs"));
after(() => rmSync(dir, { recursive: true, force: true }));
const tick = () => new Promise((resolve) => setTimeout(resolve, 2));
function setup(
  body = '<button id="start">Continuar</button><form><label>Email<input name="email" required type="email" aria-describedby="hint"></label><label>Teléfono<input name="phone" required></label><span id="hint">Privado</span></form>',
) {
  const dom = new JSDOM("<!doctype html><main>" + body + "</main>", {
    url: "https://example.test",
  });
  let snapshot = { issues: [] };
  const updates = [];
  const feedback = new FormFeedback(dom.window.document, (value) => {
    snapshot = value;
    updates.push(value);
  });
  return {
    dom,
    document: dom.window.document,
    feedback,
    updates,
    get snapshot() {
      return snapshot;
    },
    close() {
      feedback.dispose();
      dom.window.close();
    },
  };
}
test("real DOM validation groups missing fields, preserves annotations and restores focus", async () => {
  const h = setup();
  try {
    h.document.querySelector("#start").focus();
    assert.equal(h.document.querySelector("form").checkValidity(), false);
    await tick();
    assert.equal(h.snapshot.issues.length, 2);
    assert.equal(h.document.querySelectorAll(".field-error").length, 2);
    const field = h.snapshot.issues[1].target;
    h.feedback.dismiss(field);
    assert.equal(h.document.activeElement, field);
    assert.equal(h.snapshot.issues.length, 0);
    const email = h.document.querySelector("[name=email]");
    email.value = "owner@example.test";
    email.dispatchEvent(new h.dom.window.Event("input", { bubbles: true }));
    await tick();
    assert.equal(email.getAttribute("aria-invalid"), null);
    assert.equal(email.getAttribute("aria-describedby"), "hint");
    h.document.querySelector("form").checkValidity();
    await tick();
    assert.equal(h.snapshot.issues.length, 1);
    assert.equal(h.document.querySelectorAll(".field-error").length, 1);
    assert.equal(
      h.snapshot.issues[0].message,
      "Teléfono: Completa este campo para continuar.",
    );
  } finally {
    h.close();
  }
});
test("remote metadata targets the intended form regardless of wording", async () => {
  const h = setup(
    '<form id="a"><input name="outside"></form><form id="b"><input name="outside" aria-invalid="false"></form>',
  );
  try {
    const form = h.document.querySelector("#b");
    const field = form.querySelector("input");
    h.feedback.remote(
      "review",
      [
        {
          message: "Otra redacción",
          code: "outside_area_approval_required",
          field: "outside_area_approved",
        },
      ],
      form,
      { outside_area_approved: '[name="outside"]' },
    );
    assert.equal(h.snapshot.issues[0].target, field);
    assert.equal(
      h.document.querySelector("#a input").getAttribute("aria-invalid"),
      null,
    );
    h.feedback.dismiss(field);
    assert.equal(h.document.activeElement, field);
    field.dispatchEvent(new h.dom.window.Event("change", { bubbles: true }));
    await tick();
    assert.equal(field.getAttribute("aria-invalid"), "false");
    assert.equal(h.document.querySelectorAll(".field-error").length, 0);
  } finally {
    h.close();
  }
});
test("retry is explicit, repeatable and never inferred from a failure", () => {
  const h = setup();
  let attempts = 0;
  try {
    const retry = () => attempts++;
    h.feedback.remote(
      "read",
      [{ message: "Sin conexión" }],
      h.document,
      {},
      retry,
    );
    assert.equal(attempts, 0);
    const action = h.snapshot.retry;
    h.feedback.dismiss(undefined, action);
    assert.equal(attempts, 1);
    h.feedback.remote(
      "read",
      [{ message: "Sin conexión" }],
      h.document,
      {},
      retry,
    );
    assert.equal(h.snapshot.issues.length, 1);
    h.feedback.dismiss();
    assert.equal(attempts, 1);
    h.feedback.remote(
      "write",
      [{ message: "Resultado desconocido" }],
      h.document,
    );
    assert.equal(h.snapshot.retry, undefined);
  } finally {
    h.close();
  }
});
test("disposal and detached controls leave no stale annotations", async () => {
  const h = setup();
  try {
    h.feedback.remote(
      "a",
      [{ message: "Revisa email", field: "email" }],
      h.document,
    );
    h.feedback.clear("a");
    assert.equal(h.snapshot.issues.length, 0);
    assert.equal(h.document.querySelectorAll(".field-error").length, 0);
    h.feedback.remote(
      "a",
      [{ message: "Revisa email", field: "email" }],
      h.document,
    );
    h.document.querySelector("form").remove();
    h.feedback.remote("b", [{ message: "Otro error" }], h.document);
    assert.equal(h.snapshot.issues.length, 2);
    const count = h.updates.length;
    h.feedback.dispose();
    h.feedback.remote("c", [{ message: "Tarde", field: "email" }], h.document);
    await tick();
    assert.equal(h.updates.length, count);
  } finally {
    h.close();
  }
});
test("controlled custom validity is checked after input commit", async () => {
  const h = setup(
    '<form><label>Precio<input name="price" value="1"></label></form>',
  );
  try {
    const field = h.document.querySelector("input");
    field.setCustomValidity("Monto demasiado bajo");
    h.document.querySelector("form").checkValidity();
    await tick();
    h.feedback.dismiss();
    field.addEventListener("input", () => field.setCustomValidity(""));
    field.dispatchEvent(new h.dom.window.Event("input", { bubbles: true }));
    await tick();
    assert.equal(field.getAttribute("aria-invalid"), null);
  } finally {
    h.close();
  }
});
test("HTTP errors retain status, every issue and legacy detail", () => {
  const error = responseError(
    {
      detail: "Primer problema",
      errors: [
        { message: "Precio inválido", code: "greater_than", field: "price" },
        { message: "Moneda inválida", field: "currency" },
      ],
    },
    422,
  );
  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 422);
  assert.equal(error.issues.length, 2);
  assert.equal(error.issues[1].field, "currency");
  assert.equal(
    responseError({ detail: "Revisión cambió" }, 409).message,
    "Revisión cambió",
  );
  assert.deepEqual(
    responseError({ errors: { email: ["Ya existe", "Inválido"] } }, 422).issues,
    [
      { field: "email", message: "Ya existe" },
      { field: "email", message: "Inválido" },
    ],
  );
});

test("remote monetary errors focus the visible formatted field, not its hidden value", () => {
  const h = setup(
    '<button id="start">Guardar</button><form><label>Precio<input type="hidden" name="price" value="3000000"><input data-feedback-field="price" value="3,000,000"></label></form>',
  );
  try {
    h.feedback.remote(
      "price",
      [{ message: "Monto inválido", field: "price" }],
      h.document,
    );
    const target = h.snapshot.issues[0].target;
    assert.equal(target.type, "text");
    h.feedback.dismiss(target);
    assert.equal(h.document.activeElement, target);
  } finally {
    h.close();
  }
});
test("replacing an active report preserves the original return focus", () => {
  const h = setup(
    '<button id="start">Guardar</button><button id="dialog-close">Entendido</button>',
  );
  try {
    const start = h.document.querySelector("#start");
    start.focus();
    h.feedback.remote("load", [{ message: "Primera" }], h.document);
    h.document.querySelector("#dialog-close").focus();
    h.feedback.remote("load", [{ message: "Segunda" }], h.document);
    h.feedback.dismiss();
    assert.equal(h.document.activeElement, start);
  } finally {
    h.close();
  }
});
