import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { createContext, runInContext } from "node:vm";
import { test, after } from "node:test";
import ts from "typescript";

// Exercise the real handlers and their LocationMap props. Effects and the SDK
// are outside this synchronous field-edit seam; no credentials/network needed.
const source = ts.transpileModule(
  readFileSync("src/shared/components/LocationFields.tsx", "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
const editorTemp = mkdtempSync(join(tmpdir(), "maia-location-fields-"));
const editorFile = join(editorTemp, "location-editing.cjs");
writeFileSync(
  editorFile,
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
const editingModule = createRequire(import.meta.url)(editorFile);
after(() => rmSync(editorTemp, { recursive: true, force: true }));
const MapComponent = () => null;
const jsx = (type, props) => ({ type, props });
const module = { exports: {} };
runInContext(
  source,
  createContext({
    exports: module.exports,
    require: (name) => {
      if (name === "react")
        return {
          useEffect() {},
          useId: () => "test-id",
          useRef: (value) => ({ current: value }),
          useState: (value) => [value, () => {}],
        };
      if (name === "react/jsx-runtime")
        return { jsx, jsxs: jsx, Fragment: "fragment" };
      if (name.endsWith("/location-editing")) return editingModule;
      if (name.endsWith("ErrorFeedback")) return { default: "error-notice" };
      if (name.endsWith("LocationMap")) return { default: MapComponent };
      if (name.endsWith("/api"))
        return {
          api: () => {
            throw new Error("No network expected");
          },
        };
      throw new Error(name);
    },
  }),
);
const LocationFields = module.exports.default;
function nodes(element) {
  if (!element || typeof element !== "object") return [];
  if (Array.isArray(element)) return element.flatMap(nodes);
  return [element, ...nodes(element.props?.children)];
}
function setup(data) {
  let current = { ...data };
  let location = {
    id: "private-point",
    latitude: 20.677,
    longitude: -103.347,
    source: "google",
  };
  const render = () =>
    LocationFields({
      data: current,
      location,
      states: ["Jalisco"],
      signedIn: true,
      onChange: (value) => {
        current = value;
      },
      onLocation: (value) => {
        location = value;
      },
    });
  const edit = (label, value) => {
    const field = nodes(render()).find(
      (node) =>
        node.type === "label" &&
        Array.isArray(node.props.children) &&
        node.props.children.some((child) => child === label),
    );
    const control = nodes(field).find(
      (node) => node.type === "input" || node.type === "select",
    );
    assert.ok(control, label);
    control.props.onChange({ target: { value } });
    return nodes(render()).find((node) => node.type === MapComponent).props;
  };
  return { edit, current: () => current };
}

test("completing the municipality missing from Google preserves the exact marker", () => {
  const form = setup({
    private_address: "Avenida Alcalde 10",
    state: "Jalisco",
    municipality: "",
    neighborhood: "Zona Centro",
    location_ref: "private-point",
    location_confirmed: true,
  });
  const map = form.edit("Municipio", "Guadalajara");
  assert.equal(
    map.latitude,
    20.677,
    "The marker disappears when municipality clears its coordinates",
  );
  assert.equal(map.longitude, -103.347);
  assert.equal(form.current().location_ref, "private-point");
  assert.equal(form.current().location_confirmed, false);
});

test("typing all municipality characters and correcting neighborhood keep the marker pending confirmation", () => {
  const form = setup({
    private_address: "Avenida Alcalde 10",
    state: "Jalisco",
    municipality: "",
    neighborhood: "",
    location_ref: "private-point",
    location_confirmed: true,
  });
  for (const text of ["G", "Gu", "Guadalajara"])
    assert.equal(form.edit("Municipio", text).latitude, 20.677);
  assert.equal(form.edit("Colonia", "Zona Centro").longitude, -103.347);
  assert.equal(form.current().location_ref, "private-point");
  assert.equal(form.current().location_confirmed, false);
});

test("changing street or state still clears a previous exact point", () => {
  for (const [label, value] of [
    ["Busca la dirección de tu inmueble", "Otra calle 123"],
    ["Estado", "Yucatán"],
  ]) {
    const form = setup({
      private_address: "Avenida Alcalde 10",
      state: "Jalisco",
      municipality: "Guadalajara",
      location_ref: "private-point",
    });
    const map = form.edit(label, value);
    assert.equal(map.latitude, null);
    assert.equal(map.longitude, null);
    assert.equal(form.current().location_ref, null);
  }
});
