import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { test, after } from "node:test";
import ts from "typescript";
const temp = mkdtempSync(join(tmpdir(), "maia-money-"));
const file = join(temp, "money.cjs");
writeFileSync(
  file,
  ts.transpileModule(readFileSync("src/shared/lib/money-input.ts", "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
);
const { parseMoneyInput, formatMoneyInput, moneyCaret } = createRequire(
  import.meta.url,
)(file);
after(() => rmSync(temp, { recursive: true, force: true }));
test("amounts display comma grouping while API/form values remain unformatted", () => {
  for (const [raw, displayed] of [
    ["3000000", "3,000,000"],
    ["2000", "2,000"],
    ["1234567.50", "1,234,567.50"],
    ["0", "0"],
    ["", ""],
  ]) {
    assert.equal(formatMoneyInput(raw), displayed);
    assert.equal(parseMoneyInput(displayed), raw);
  }
});
test("decimal entry and cents survive without rounding or losing trailing zeros", () => {
  assert.equal(formatMoneyInput("1234."), "1,234.");
  assert.equal(parseMoneyInput(".50"), "0.50");
  assert.equal(parseMoneyInput("0001234.50"), "1234.50");
  assert.equal(formatMoneyInput("999999999999.99"), "999,999,999,999.99");
  for (const value of ["-1", "12.345", "1e6", "abc", "12.3.4"])
    assert.equal(parseMoneyInput(value), null);
});
test("caret tracks digits and decimal point through inserted thousands separators", () => {
  assert.equal(moneyCaret("3,000,000", 1), 1);
  assert.equal(moneyCaret("3,000,000", 4), 5);
  assert.equal(moneyCaret("1,234.50", 5), 6);
  assert.equal(moneyCaret("1,234.50", 7), 8);
});
