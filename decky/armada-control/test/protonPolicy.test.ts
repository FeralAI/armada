import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultWindowsCompatTool,
} from "../src/lib/protonPolicy.ts";

const tool = (id: string) => ({ id, label: id });
const experimental = "proton-experimental-arm64";
const stable = "proton-stable-arm64";
const cachyos = "proton-cachyos-11.0-arm64";
const defaults = [experimental, stable, cachyos];

test("candidate order wins over installed-tool order", () => {
  assert.equal(defaultWindowsCompatTool([
    tool(cachyos),
    tool(stable),
    tool(experimental),
  ], defaults), experimental);
});

test("missing candidates are skipped", () => {
  assert.equal(defaultWindowsCompatTool([
    tool(stable),
    tool(cachyos),
  ], defaults), stable);
});

test("a device-specific list can require CachyOS", () => {
  assert.equal(defaultWindowsCompatTool([
    tool(experimental),
    tool(cachyos),
  ], [cachyos]), cachyos);
});

test("no unavailable candidate is selected", () => {
  assert.equal(defaultWindowsCompatTool([
    tool("proton_experimental"),
    tool("proton-stable"),
  ], defaults), "");
});
