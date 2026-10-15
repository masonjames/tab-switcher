import { test, expect } from "bun:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

function fixture() {
  const messages = [], activations = [];
  const timers = new Map();
  let timerID = 0;
  const event = () => { const listeners = []; return { addListener(fn) { listeners.push(fn); }, emit(...args) { listeners.forEach(fn => fn(...args)); } }; };
  let focusedWindow = 1;
  let listener;
  let paused;
  const tabs = new Map(Array.from({ length: 9 }, (_, i) => [i + 1, {
    id: i + 1, windowId: i === 1 ? 2 : 1, title: `Tab ${i + 1}`,
  }]));
  const port = { postMessage: m => messages.push(m), onMessage: { addListener(fn) { listener = fn; } }, onDisconnect: event() };
  const chrome = {
    runtime: { getManifest: () => ({ version: "3.7.5" }), onInstalled: event(), onStartup: event(), onMessage: event(), connectNative: () => port },
    commands: { onCommand: event() }, storage: { local: { set() {} } },
    windows: {
      getAll: async (_options, callback) => {
        if (callback) { callback([]); return; }
        if (paused) { const pending = paused; paused = null; await pending; }
        return [1, 2].map(id => ({ id, focused: id === focusedWindow }));
      },
      getCurrent: async () => ({ id: focusedWindow }), update: async id => { focusedWindow = id; chrome.windows.onFocusChanged.emit(id); }, onFocusChanged: event(),
    },
    tabs: {
      query: async options => [...tabs.values()].filter(tab => tab.windowId === options.windowId),
      get: async id => { if (!tabs.has(id)) throw new Error("Closed"); return tabs.get(id); },
      update: async id => {
        const tab = tabs.get(id);
        for (const other of tabs.values()) if (other.windowId === tab.windowId) other.active = other.id === id;
        activations.push(id);
        chrome.tabs.onActivated.emit({ tabId: id, windowId: tab.windowId });
      },
      onActivated: event(), onUpdated: event(), onCreated: event(), onRemoved: event(),
    },
  };
  const context = vm.createContext({ chrome, navigator: { userAgent: "Chrome" }, console: { log() {} },
    setInterval() {}, setTimeout(fn) { timers.set(++timerID, fn); return timerID; }, clearTimeout(id) { timers.delete(id); }, fetch: () => Promise.reject(new Error("offline test")) });
  vm.runInContext(readFileSync(new URL("../mainsw.js", import.meta.url), "utf8"), context);
  vm.runInContext("mru = [1, 2, 3, 4, 5, 6, 7, 8, 9]", context);
  return { context, messages, activations, tabs,
    request() {
      const responses = [];
      chrome.runtime.onMessage.emit({ action: "ping_native_host" }, {}, r => responses.push(r));
      return { responses, id: messages.at(-1).requestId };
    },
    timeout() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()); },
    disconnect() { port.onDisconnect.emit(); },
    focus(windowId, activeTabId) {
      focusedWindow = windowId;
      for (const tab of tabs.values()) if (tab.windowId === windowId) tab.active = tab.id === activeTabId;
      chrome.windows.onFocusChanged.emit(windowId);
    }, send: m => listener(m),
    pause() { let resume; paused = new Promise(resolve => { resume = resolve; }); return resume; },
    done: () => vm.runInContext("nativeSwitchQueue", context) };
}
const cycle = (action = "cycle_next", extra = {}) => ({ action, show_ui: true, current_window_only: true, ...extra });

test("immediate release waits for initial async cycle, commits filtered MRU, preserves A/B", async () => {
  const f = fixture();
  const resume = f.pause();
  f.send(cycle()); f.send({ action: "end_switch" });
  await Promise.resolve();
  expect(f.activations).toEqual([]);
  resume(); await f.done();
  expect(f.activations).toEqual([3]);
  expect(vm.runInContext("mru[0]", f.context)).toBe(3);
  expect(f.messages.filter(m => m.action === "show_switcher")[0].selectedIndex).toBe(1);
  expect(f.messages.filter(m => m.action !== "ping").at(-1).action).toBe("hide_switcher");
  f.send(cycle()); f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([3, 1]);
});
test("forward and reverse stay in one frozen session with five cards", async () => {
  const f = fixture();
  f.send(cycle()); f.send(cycle()); f.send(cycle("cycle_prev"));
  f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([3]);
  const shown = f.messages.filter(m => m.action === "show_switcher");
  expect(shown).toHaveLength(1);
  expect(shown[0].tabs.map(t => t.id)).toEqual([1, 3, 4, 5, 6]);
  expect(f.messages.filter(m => m.action === "update_selection").map(m => m.selectedIndex)).toEqual([2, 1]);
});
test("reverse wraps and explicit limit applies after window filtering", async () => {
  const f = fixture();
  f.send(cycle("cycle_prev", { recent_tab_limit: 5 }));
  f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([6]);
});
test("closed tabs cannot shift card indices; empty current window never crosses windows", async () => {
  const f = fixture(); f.tabs.delete(3);
  f.send(cycle()); f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([4]);
  for (const [id, tab] of f.tabs) if (tab.windowId === 1) f.tabs.delete(id);
  vm.runInContext("mru = [2]", f.context);
  f.send(cycle()); f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([4]);
});
test("rapid release then new session commits in order and all-window mode remains available", async () => {
  const f = fixture();
  f.send(cycle("cycle_next", { current_window_only: false }));
  f.send({ action: "end_switch" });
  f.send(cycle("cycle_next", { current_window_only: false }));
  f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([2, 1]);
});


test("all-windows focus-only change reconciles current tab before five-card limit", async () => {
  const f = fixture();
  // No onActivated event: focusing an existing window must still anchor its active tab.
  f.tabs.get(9).windowId = 2;
  f.focus(2, 9);
  f.send(cycle("cycle_next", { current_window_only: false }));
  await f.done();
  const shown = f.messages.find(m => m.action === "show_switcher");
  expect(shown.tabs.map(t => t.id)).toEqual([9, 1, 2, 3, 4]);
  expect(shown.selectedIndex).toBe(1);
  f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([1]);
  f.send(cycle("cycle_next", { current_window_only: false }));
  f.send({ action: "end_switch" }); await f.done();
  expect(f.activations).toEqual([1, 9]);
});


test("connected permission denial recovers only from a fresh correlated health response", () => {
  const f = fixture();
  const first = f.request();
  f.send({ action: "error_no_accessibility" });
  f.send({ action: "pong", requestId: first.id, shortcutHealth: "permissionDenied" });
  expect(first.responses).toEqual([{ connected: true, shortcutHealth: "permissionDenied" }]);
  const second = f.request();
  f.send({ action: "pong", requestId: first.id, shortcutHealth: "ready" });
  expect(second.responses).toEqual([]);
  f.send({ action: "pong", requestId: second.id, shortcutHealth: "ready" });
  expect(second.responses).toEqual([{ connected: true, shortcutHealth: "ready" }]);
});

test("legacy and missing or invalid health never indicate readiness", () => {
  for (const extra of [{}, { shortcutHealth: "ready" }, { shortcutHealth: "invalid" }]) {
    const f = fixture(); const request = f.request();
    f.send({ action: "pong", ...extra });
    expect(request.responses).toEqual([{ connected: true, shortcutHealth: "unknown" }]);
  }
  const f = fixture(); const request = f.request();
  f.send({ action: "pong", requestId: request.id });
  expect(request.responses).toEqual([{ connected: true, shortcutHealth: "unknown" }]);
});

test("overlapping refresh requests each resolve once; disconnect and timeout are bounded", () => {
  const f = fixture(); const first = f.request(); const second = f.request();
  f.send({ action: "pong", requestId: second.id, shortcutHealth: "listenerUnavailable" });
  expect(first.responses).toEqual([]);
  expect(second.responses).toEqual([{ connected: true, shortcutHealth: "listenerUnavailable" }]);
  f.disconnect();
  expect(first.responses).toEqual([{ connected: false, shortcutHealth: "unknown" }]);
  f.send({ action: "pong", requestId: first.id, shortcutHealth: "ready" });
  expect(first.responses).toHaveLength(1);
  expect(second.responses).toHaveLength(1);
  const g = fixture(); const timed = g.request(); g.timeout();
  expect(timed.responses).toEqual([{ connected: false, shortcutHealth: "unknown" }]);
});

test("health timeout preserves an established transport and background pongs cannot cancel a probe", () => {
  const f = fixture();
  f.send({ action: "registered" });
  const request = f.request();
  f.focus(1, 1);
  const background = f.messages.find(m => m.action === "ping" && m.requestId.includes(":background:"));
  expect(background).toBeDefined();
  f.send({ action: "pong", requestId: background.requestId, shortcutHealth: "ready" });
  expect(request.responses).toEqual([]);
  f.send({ action: "pong", requestId: "wrong-request", shortcutHealth: "ready" });
  f.timeout();
  expect(request.responses).toEqual([{ connected: true, shortcutHealth: "unknown" }]);
});
