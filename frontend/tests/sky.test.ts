// lib/sky.ts 的单测（= App test/sky_test.dart 的插值半边）：关键帧之间线性插值、整点落在时段上、跨午夜回绕。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { SKY_PARTS, SKY_PHASES, lerpHex, skyAt, type SkyTable } from "../src/lib/sky.ts";

/** 直接从 tokens.css 读浅 / 深两张表（与运行时 getComputedStyle 读的是同一份），连同那套主题的 --text / --text-2 / --text-3。 */
const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const readTheme = (selector: RegExp) => {
  const block = selector.exec(css)![1];
  const t = {} as SkyTable;
  for (const ph of SKY_PHASES) {
    t[ph] = {} as SkyTable[typeof ph];
    for (const p of SKY_PARTS) t[ph][p] = new RegExp(`--sky-${ph}-${p}:\\s*(#[0-9a-f]{6})`).exec(block)![1];
  }
  const ink = (k: string) => new RegExp(`--${k}:\\s*(#[0-9a-f]{6})`).exec(block)![1];
  return { sky: t, text: ink("text"), text2: ink("text-2"), text3: ink("text-3") };
};
const lightTheme = readTheme(/:root\s*\{([\s\S]*?)\}/);
const darkTheme = readTheme(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\}/);
const light = lightTheme.sky;

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

// v3.3 B2：壁纸上真实出现的颜色（钟点插值 × 底色按 Sky.ramp 取 11 个高度 × 叠上三团柔光峰值，= App test/sky_test.dart 同一采样），
// 正文 / 次要字 ≥ 4.5、最次要字 ≥ 3（浅深两套）。柔光强度读 base.css 的 --mix，底色曲线 = App Sky.rampPow 0.75。
const baseCss = readFileSync(new URL("../src/styles/base.css", import.meta.url), "utf8");
const BLOB_MIX = ["a", "b", "c"].map((k) => Number(new RegExp(`\\.sky-${k}\\s*\\{[^}]*--mix:\\s*([\\d.]+)`).exec(baseCss)![1]));
const ramp = (y: number) => { const x = y ** 0.75; return x * x * (3 - 2 * x); };
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)]; return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const worstOn = (table: SkyTable, fg: string) => {
  let worst = Infinity;
  for (let q = 0; q < 96; q++) {
    const c = skyAt(table, q / 4);
    for (let i = 0; i <= 10; i++) {
      const base = lerpHex(c.top, c.bottom, ramp(i / 10));
      for (const bg of [base, lerpHex(base, c.a, BLOB_MIX[0]), lerpHex(base, c.b, BLOB_MIX[1]), lerpHex(base, c.c, BLOB_MIX[2])]) worst = Math.min(worst, contrast(fg, bg));
    }
  }
  return worst;
};

for (const [name, th] of [["浅色", lightTheme], ["深色", darkTheme]] as const) {
  test(`${name}：正文 / 次要字对壁纸全天每一处 ≥ 4.5，最次要字 ≥ 3`, () => {
    assert.equal(BLOB_MIX.length, 3);
    for (const [what, fg, min] of [["正文", th.text, 4.5], ["次要字", th.text2, 4.5], ["最次要字", th.text3, 3]] as const) {
      const w = worstOn(th.sky, fg);
      assert.ok(w >= min, `${name}${what} ${fg} 对壁纸最差 ${w.toFixed(2)}:1（要 ≥${min}）`);
    }
  });
}
