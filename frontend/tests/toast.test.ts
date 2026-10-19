// lib/toast.ts 的单测（= App test/toast_test.dart 的网页半边）：短提示 2 秒消失、带按钮的也定时消失、新替旧不排队。
import assert from "node:assert/strict";
import { beforeEach, mock, test } from "node:test";
import { TOAST_ACTION_MS, TOAST_EXIT_MS, TOAST_MS, dismissToast, toast, toastCurrent, toastReset } from "../src/lib/toast.ts";

beforeEach(() => {
  mock.timers.reset();
  mock.timers.enable({ apis: ["setTimeout"] });
  toastReset();
});

test("短提示到时自动收起：先淡出再移除", () => {
  toast("已复制");
  mock.timers.tick(TOAST_MS - 1);
  assert.equal(toastCurrent()?.leaving, false);
  mock.timers.tick(1);
  assert.equal(toastCurrent()?.leaving, true);
  mock.timers.tick(TOAST_EXIT_MS);
  assert.equal(toastCurrent(), null);
});

test("带“撤销”的也定时消失，只是多留一会儿", () => {
  toast("已移除", { action: "撤销", onAction: () => {} });
  mock.timers.tick(TOAST_MS);
  assert.equal(toastCurrent()?.leaving, false);
  mock.timers.tick(TOAST_ACTION_MS - TOAST_MS);
  assert.equal(toastCurrent()?.leaving, true);
  mock.timers.tick(TOAST_EXIT_MS);
  assert.equal(toastCurrent(), null);
});

test("连点不排队：新替旧，最后一条从它出现起计时", () => {
  for (let i = 0; i < 5; i++) {
    toast(`第 ${i} 条`);
    assert.equal(toastCurrent()?.text, `第 ${i} 条`);
    mock.timers.tick(300);
  }
  mock.timers.tick(TOAST_MS - 300);
  assert.equal(toastCurrent()?.leaving, true);
  mock.timers.tick(TOAST_EXIT_MS);
  assert.equal(toastCurrent(), null, "旧的计时器全部作废，不会再冒出排队的");
});

test("点一下关掉；退场中再来一条立刻换上", () => {
  toast("A");
  dismissToast();
  assert.equal(toastCurrent()?.leaving, true);
  toast("B");
  assert.deepEqual([toastCurrent()?.text, toastCurrent()?.leaving], ["B", false]);
  mock.timers.tick(TOAST_EXIT_MS);
  assert.equal(toastCurrent()?.text, "B", "A 的退场计时不会把 B 撤掉");
});
