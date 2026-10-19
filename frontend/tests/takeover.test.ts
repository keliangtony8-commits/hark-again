// 接管页换算（= App test/browser_handoff_test.dart）：点哪落哪 + 点一下按住的真实时长。
// 画面框本身由 CSS 做成 contain（blocks.css .takeover-screen），BrowserTakeover 按这个框换算，所以框内 = 0–1 满幅。
import { test } from "node:test";
import assert from "node:assert/strict";
import { takeoverFit, takeoverHold, takeoverPoint } from "../src/lib/browserView.ts";

test("按画面框换算：框 = 1280×800 的等比缩放时，框内点 → 0–1，四角不越界", () => {
  const w = 1494, h = 933.75; // 1920×1080 窗口里的画面框
  assert.deepEqual(takeoverFit(w, h), { left: 0, top: 0, width: w, height: h });
  const p = takeoverPoint((222 / 1280) * w, (312 / 800) * h, w, h)!; // 网页 (222, 312)：真站 Turnstile 复选框的位置
  assert.ok(Math.abs(p.x * 1280 - 222) < 0.01 && Math.abs(p.y * 800 - 312) < 0.01);
  assert.deepEqual(takeoverPoint(0, 0, w, h), { x: 0, y: 0 });
  assert.deepEqual(takeoverPoint(w, h, w, h), { x: 1, y: 1 });
});

test("宽舞台：留边处不点；画面区按 contain 换算", () => {
  const f = takeoverFit(1872, 934);
  assert.equal(Math.round(f.left), 189);
  assert.equal(takeoverPoint(100, 400, 1872, 934), null);
});

test("按住时长 = 抬起 − 按下，取整、不为负", () => {
  assert.equal(takeoverHold(1000, 1093.6), 94);
  assert.equal(takeoverHold(1000, 990), 0);
});
