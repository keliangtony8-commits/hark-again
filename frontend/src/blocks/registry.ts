import type { ComponentType } from "react";
import type { Block } from "../lib/types";
import TextBlock from "./TextBlock";
import TableBlock from "./TableBlock";
import LinksBlock from "./LinksBlock";
import CodeBlock from "./CodeBlock";
import FileBlock from "./FileBlock";
import ApprovalBlock from "./ApprovalBlock";
import BrowserBlock from "./BrowserBlock";
import PageBlock from "./PageBlock";
import StatsBlock from "./StatsBlock";
import MemoryBlock from "./MemoryBlock";

// 新增一种卡片：写组件 → 在这里登记。渲染器和聊天流程不用改。
export const registry: { [K in Block["type"]]: ComponentType<{ block: Extract<Block, { type: K }> }> } = {
  text: TextBlock,
  table: TableBlock,
  links: LinksBlock,
  code: CodeBlock,
  file: FileBlock,
  approval: ApprovalBlock,
  browser: BrowserBlock,
  page: PageBlock,
  stats: StatsBlock,
  memory: MemoryBlock,
};
