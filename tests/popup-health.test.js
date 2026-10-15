import { test, expect } from "bun:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

function popup(name = "Tab Switcher Local") {
  const elements = new Map();
  const callbacks = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, { textContent: "", className: "", disabled: false, addEventListener(_event, handler) { this.click = handler; } });
    return elements.get(id);
  };
  const chrome = { runtime: {
    sendMessage(message, callback) { if (message.action === "ping_native_host") callbacks.push(callback); },
    getManifest: () => ({ version: "3.7.5", name }),
  }, storage: { local: { get(_key, callback) { callback({}); } } } };
  vm.runInNewContext(readFileSync(new URL("../popup.js", import.meta.url), "utf8"), {
    chrome, document: { getElementById: element },
  });
  return { element, callbacks };
}

test("popup distinguishes denied permission, recovery, unknown and offline using safe text", () => {
  const p = popup();
  p.callbacks[0]({ connected: true, shortcutHealth: "permissionDenied" });
  expect(p.element("status-text").textContent).toBe("App connected — shortcuts unavailable");
  expect(p.element("health-detail").textContent).toContain("switch is ON");
  expect(p.element("health-detail").textContent).toContain("/Applications/Tab Switcher Local.app");
  expect(p.element("status").className).toBe("status warning");
  p.element("refresh-health").click();
  p.callbacks[1]({ connected: true, shortcutHealth: "ready" });
  expect(p.element("status-text").textContent).toBe("Shortcuts ready");
  p.element("refresh-health").click();
  p.callbacks[2]({ connected: true, shortcutHealth: "<img onerror=alert(1)>" });
  expect(p.element("health-detail").textContent).toContain("update the app");
  expect(p.element("status-text").textContent).toBe("App connected — shortcut status unknown");
  expect(p.element("health-detail").innerHTML).toBeUndefined();
  p.element("refresh-health").click();
  p.callbacks[3]({ connected: false });
  expect(p.element("status").className).toBe("status disconnected");
  expect(p.element("refresh-health").disabled).toBe(false);
});

test("popup ignores an old ready callback after a newer refresh", () => {
  const p = popup();
  p.element("refresh-health").click();
  p.callbacks[1]({ connected: true, shortcutHealth: "originalConflict" });
  p.callbacks[0]({ connected: true, shortcutHealth: "ready" });
  expect(p.element("status").className).toBe("status warning");
  expect(p.element("health-detail").textContent).toContain("original companion");
});

test("permission guidance matches the packaged companion identity", () => {
  const p = popup("Tab Switcher");
  p.callbacks[0]({ connected: true, shortcutHealth: "permissionDenied" });
  expect(p.element("health-detail").textContent).toContain("/Applications/Tab Switcher.app");
  expect(p.element("health-detail").textContent).not.toContain("Tab Switcher Local");
});
