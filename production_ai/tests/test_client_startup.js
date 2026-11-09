const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "mira_archive.html"), "utf8")
  .match(/<script>([\s\S]*?)<\/script>/)[1];
const user = { id: "test-admin", userId: "eomms0110", name: "Test", role: "admin", status: "approved", permissions: [] };
const records = [
  { id: "numbered", entryType: "roasting", blend: "올드독", batch: "#1", roastDate: "2026-10-20", roastData: {} },
  { id: "text-batch", entryType: "roasting", blend: "올드독", batch: "비정형 배치", roastDate: "2026-10-20", roastData: {} },
  { id: "custom-blend", entryType: "roasting", blend: "테스트 커피", batch: "테스트 커피1", roastDate: "2026-10-20", roastData: {} },
  { id: "cupping", entryType: "cupping", blend: "올드독", batch: "#1", roastDate: "2026-10-20", verdict: "pass", note: "OK" }
];

function runStartup(sharedStore, options = {}) {
  const elements = new Map();
  const listeners = new Map();
  const values = new Set(["value", "innerHTML", "textContent", "className", "href", "id", "type", "placeholder", "title", "innerText"]);
  function element(selector) {
    if (elements.has(selector)) return elements.get(selector);
    const state = { style: {}, dataset: {}, checked: false, hidden: false, options: [], selectedOptions: [], children: [], files: [] };
    const noop = () => undefined;
    const proxy = new Proxy(function () {}, {
      get(_, key) {
        if (key === Symbol.toPrimitive) return () => "";
        if (key === Symbol.iterator) return function* () {};
        if (key === "then") return undefined;
        if (key === "classList") return { add: noop, remove: noop, toggle: noop, contains: () => false };
        if (key === "querySelector") return (child) => element(selector + child);
        if (key === "querySelectorAll") return () => [];
        if (key === "addEventListener") return (type, handler) => {
          const eventKey = selector + ":" + type;
          if (!listeners.has(eventKey)) listeners.set(eventKey, []);
          listeners.get(eventKey).push(handler);
        };
        if (key === "closest") return () => null;
        if (key === "matches") return () => false;
        if (key === "length") return 0;
        if (key in state) return state[key];
        return values.has(key) ? "" : noop;
      },
      set(_, key, value) { state[key] = value; return true; },
      apply() {}
    });
    elements.set(selector, proxy);
    return proxy;
  }
  const requests = [];
  class FakeXHR {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send(body) {
      requests.push([this.method, this.url]);
      if (this.method === "PUT" && options.allowWrites) {
        this.status = options.writeStatus || 200;
        options.onWrite?.(JSON.parse(body), this.url);
        this.responseText = JSON.stringify(this.status === 200 ? {ok:true} : {error:"Test save failure"});
        return;
      }
      assert.equal(this.method, "GET", "startup must not write records");
      assert.equal(this.url, "/api/bootstrap");
      this.status = 200;
      this.responseText = JSON.stringify({ user, users: [user], store: sharedStore });
    }
  }
  const storage = new Map([["mira_blend_qc_session_v1", JSON.stringify({ userId: user.id })]]);
  const localStorage = {
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key)
  };
  const context = vm.createContext({
    console, URL, Blob, Date, XMLHttpRequest: FakeXHR, localStorage, sessionStorage: localStorage,
    location: { protocol: "https:", hostname: "test.invalid", origin: "https://test.invalid", search: "", hash: "", href: "https://test.invalid/" },
    document: { querySelector: element, querySelectorAll: () => [], getElementById: element, createElement: element, addEventListener() {}, body: element("body") },
    navigator: { userAgent: "test" }, FileReader: class {},
    setTimeout() {}, addEventListener() {}, requestAnimationFrame: (callback) => callback(),
    alert() {}, confirm: () => true, matchMedia: () => element("media"), history: element("history")
  });
  context.window = context;
  vm.runInContext(source, context);
  assert.equal(requests.length, 1);
  return { context, elements, requests, listeners };
}

const fixture = {
  mira_blend_qc_entries_v1: records,
  mira_blend_qc_ratio_notices_v1: [{ id: "ratio", blend: "테스트 커피", effectiveDate: "2026-10-20" }]
};
const { context } = runStartup(fixture);
assert.equal(vm.runInContext("entries.length", context), records.length, "one text batch must not blank every record");
assert.equal(vm.runInContext('entries.find((entry) => entry.id === "numbered").verdict', context), "pass");
assert.equal(vm.runInContext('entries.find((entry) => entry.id === "custom-blend").batch', context), "#1");
assert.deepEqual(JSON.parse(JSON.stringify(fixture.mira_blend_qc_entries_v1)), records);
assert.equal(vm.runInContext("entries.length", runStartup({}).context), 0);
console.log("Client startup: text batches, custom blends, verdict sync and read-only bootstrap passed.");
module.exports = { runStartup };
