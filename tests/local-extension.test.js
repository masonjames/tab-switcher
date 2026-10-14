import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";

test("generated local extension identity matches app authorization and preserves upstream source", () => {
  // Run build-local.sh first; it generates this inspectable, uninstalled artifact pair.
  const source = JSON.parse(readFileSync("manifest.json", "utf8"));
  const local = JSON.parse(readFileSync("dist/extension-local/manifest.json", "utf8"));
  const publicKey = readFileSync("native-host/local-extension/public-key.txt", "utf8").trim();
  expect(local.key).toBe(publicKey);
  expect(source.key).toBeUndefined();
  const hash = createHash("sha256").update(Buffer.from(local.key, "base64")).digest("hex").slice(0, 32);
  const id = [...hash].map(char => String.fromCharCode(97 + parseInt(char, 16))).join("");
  const plist = JSON.parse(execFileSync("plutil", ["-convert", "json", "-o", "-", "dist/Tab Switcher Local.app/Contents/Info.plist"], { encoding: "utf8" }));
  expect(plist.TabSwitcherLocalExtensionID).toBe(id);
  expect(plist.CFBundleVersion).toMatch(/^\d+(\.\d+){0,2}$/);
  expect(readFileSync("dist/extension-local/mainsw.js", "utf8")).toContain('connectNative("com.masonjames.tabswitcher.local")');
  expect(readFileSync("mainsw.js", "utf8")).toContain('connectNative("com.tabswitcher.native")');
  expect(local.background).toEqual(source.background);
  for (const file of [local.background.service_worker, local.action.default_popup, ...Object.values(local.icons)]) {
    expect(readFileSync(`dist/extension-local/${file}`).length).toBeGreaterThan(0);
  }
});
