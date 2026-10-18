// v3.5.2 项目 = 目录：项目内 ☰ 只在“从目录进来”时退一页，其余（深链、别处跳来、聊天屏的跳转状态）都去 /projects。
import { test } from "node:test";
import assert from "node:assert/strict";
import { DIR_ENTRY, cameFromDirectory } from "../src/features/projects/directory.ts";

test("从项目目录进来的标记才算", () => {
  assert.equal(cameFromDirectory(DIR_ENTRY), true);
  assert.equal(cameFromDirectory(null), false);
  assert.equal(cameFromDirectory(undefined), false);
  assert.equal(cameFromDirectory({ open: "c1", focus: "m1" }), false);
  assert.equal(cameFromDirectory("fromDirectory"), false);
});
