// lib/swr.ts 的单测（= App test/swr_test.dart 的网页半边）。node 22 原生跑 TS：npm test。
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { SWR_MAX, swrCache, swrClear, swrFetch, swrMutate, swrPatch, swrSubscribe, swrWrite } from "../src/lib/swr.ts";

beforeEach(() => swrClear());

test("二次进入：缓存里有就直接给（不经过加载态）", async () => {
  await swrFetch("/a", async () => ({ n: 1 }));
  assert.deepEqual(swrCache.peek("/a"), { n: 1 });
});

test("后台刷新：新数据替换旧数据并通知；数据没变不通知", async () => {
  swrWrite("/a", { n: 1 });
  let hits = 0;
  const off = swrSubscribe("/a", () => hits++);
  await swrFetch("/a", async () => ({ n: 1 }));
  assert.equal(hits, 0, "相同 JSON 不发新状态");
  await swrFetch("/a", async () => ({ n: 2 }));
  assert.equal(hits, 1);
  assert.deepEqual(swrCache.peek("/a"), { n: 2 });
  off();
});

test("有缓存时出错：旧数据保留，错误抛给调用方（由 useSwr 决定不打扰）", async () => {
  swrWrite("/a", [1, 2]);
  await assert.rejects(swrFetch("/a", async () => { throw new Error("断网"); }));
  assert.deepEqual(swrCache.peek("/a"), [1, 2]);
});

test("同一把键并发只发一个请求", async () => {
  let calls = 0;
  const f = () => new Promise<number>((r) => { calls++; setTimeout(() => r(7), 5); });
  const [x, y] = await Promise.all([swrFetch("/a", f), swrFetch("/a", f)]);
  assert.equal(calls, 1);
  assert.equal(x, 7); assert.equal(y, 7);
});

test("LRU：最多 SWR_MAX 条，最久没用的先丢，读过的挪到最新", () => {
  for (let i = 0; i < SWR_MAX; i++) swrWrite(`/k${i}`, i);
  swrCache.read("/k0"); // k0 刚用过
  swrWrite("/new", 1);
  assert.equal(swrCache.size(), SWR_MAX);
  assert.ok(swrCache.has("/k0"));
  assert.ok(!swrCache.has("/k1"), "最久没用的 k1 被挤掉");
});

test("退出登录清空；清空前发出的请求回来也不写入", async () => {
  swrWrite("/me", { name: "a" });
  let resolve!: (v: unknown) => void;
  const p = swrFetch("/secret", () => new Promise((r) => { resolve = r; }));
  swrClear();
  assert.equal(swrCache.size(), 0);
  resolve({ token: "x" });
  await p;
  assert.ok(!swrCache.has("/secret"));
});

test("mutate / patch：增删改写回缓存；patch 没缓存不凭空造", () => {
  swrMutate<number[]>("/list", (old) => [...(old ?? []), 1]);
  assert.deepEqual(swrCache.peek("/list"), [1]);
  swrPatch<number[]>("/none", (l) => [...l, 1]);
  assert.ok(!swrCache.has("/none"));
  swrPatch<number[]>("/list", (l) => l.filter((x) => x !== 1));
  assert.deepEqual(swrCache.peek("/list"), []);
});
