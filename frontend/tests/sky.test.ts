// lib/sky.ts 的单测（= App test/sky_test.dart 的插值半边）：关键帧之间线性插值、整点落在时段上、跨午夜回绕。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { SKY_PARTS, SKY_PHASES, lerpHex, skyAt, type SkyTable } from "../src/lib/sky.ts";

/** 直接从 tokens.css 读浅色那张表（与运行时 getComputedStyle 读的是同一份）。 */
const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const light = (() => {
  const block = /:root\s*\{([\s\S]*?)\}/.exec(css)![1];
  const t = {} as SkyTable;
  for (const ph of SKY_PHASES) {
    t[ph] = {} as SkyTable[typeof ph];
    for (const p of SKY_PARTS) t[ph][p] = new RegExp(`--sky-${ph}-${p}:\\s*(#[0-9a-f]{6})`).exec(block)![1];
  }
  return t;
})();

test("lerpHex 逐通道线性", () => {
  assert.equal(lerpHex("#000000", "#ffffff", 0.5), "#808080");
  assert.equal(lerpHex("#102030", "#102030", 0.3), "#102030");
  assert.equal(lerpHex("#000000", "#ff0000", 1), "#ff0000");
});

test("时段中间就是那个时段的颜色", () => {
  assert.deepEqual(skyAt(light, 12), light.day);
  assert.deepEqual(skyAt(light, 2), light.night);
  assert.deepEqual(skyAt(light, 22), light.night);
  assert.deepEqual(skyAt(light, 6), light.dawn);
});

test("黎明 / 黄昏在相邻两帧之间线性过渡", () => {
  const mid = skyAt(light, 5.25); // 4.5 夜 → 6.0 黎明 的正中
  for (const p of SKY_PARTS) assert.equal(mid[p], lerpHex(light.night[p], light.dawn[p], 0.5));
  const dusk = skyAt(light, 17.5); // 16.5 白天 → 18.5 黄昏 的正中
  for (const p of SKY_PARTS) assert.equal(dusk[p], lerpHex(light.day[p], light.dusk[p], 0.5));
});

test("钟点回绕：24 点 = 0 点，负数也能算", () => {
  assert.deepEqual(skyAt(light, 24), skyAt(light, 0));
  assert.deepEqual(skyAt(light, -1), skyAt(light, 23));
});
