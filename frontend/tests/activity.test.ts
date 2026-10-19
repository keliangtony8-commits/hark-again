// v3.5.5 步骤胶囊文案（= App test/activity_test.dart 同规则）：生成中只说当前那一步，两步之间“正在思考”；完成后“N 个步骤 · 用时”。
import { test } from "node:test";
import assert from "node:assert/strict";
import { activitySummary, capsuleLabel } from "../src/lib/activity.ts";
import type { ActivityStep } from "../src/lib/types.ts";

const step = (id: string, title: string, detail: string, state: ActivityStep["state"], at?: string, ms?: number): ActivityStep =>
  ({ id, tool: "run_command", title, detail, state, at, ms });

test("生成中：最后一个进行中的步骤；没有进行中的 = 正在思考", () => {
  assert.deepEqual(capsuleLabel([step("a", "读文件", "a.txt", "done"), step("b", "运行命令", "ls", "running")]), ["正在运行命令", "ls"]);
  assert.deepEqual(capsuleLabel([step("a", "读文件", "a.txt", "done")]), ["正在思考", ""]);
});

test("完成后：N 个步骤 · 整段用时；没时间不报用时", () => {
  const at = "2026-10-19T10:00:00Z";
  assert.equal(activitySummary([step("a", "读文件", "", "done", at, 300), step("b", "运行命令", "", "done", "2026-10-19T10:00:05Z", 7000)]), "2 个步骤 · 12 秒");
  assert.equal(activitySummary([step("a", "搜索", "", "done")]), "1 个步骤");
});
