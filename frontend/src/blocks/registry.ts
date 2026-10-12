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
import { DraftBlock, ImagesBlock, SummaryBlock } from "./ContentBlocks";
import { OrderBlock, ProductsBlock } from "./CommerceBlocks";
import FormBlock from "./FormBlock";
import JobBlock from "./JobBlock";
import PreviewBlock from "./PreviewBlock";

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
  draft: DraftBlock,
  summary: SummaryBlock,
  images: ImagesBlock,
  products: ProductsBlock,
  order: OrderBlock,
  form: FormBlock,
  job: JobBlock,
  preview: PreviewBlock,
};

/** 卡片类块（v0.84，和 App models/block.dart standsAlone 同一份名单）：要扫一眼或要点的，单独成卡、占满聊天区，不套在回复卡里。 */
export const STANDALONE: ReadonlySet<Block["type"]> = new Set<Block["type"]>(["approval", "order", "form", "products", "summary", "browser", "job"]);

export type ReplySegment = { card: boolean; blocks: Block[] };

/** 回复按段排：连续正文类块合成一段（一张回复卡），卡片块各自成段；不认识的块不占位、不切开正文。 */
export function replySegments(blocks: Block[]): ReplySegment[] {
  const out: ReplySegment[] = [];
  let prose: Block[] = [];
  for (const b of blocks) {
    if (!(b.type in registry)) continue;
    if (!STANDALONE.has(b.type)) { prose.push(b); continue; }
    if (prose.length) out.push({ card: false, blocks: prose });
    prose = [];
    out.push({ card: true, blocks: [b] });
  }
  if (prose.length) out.push({ card: false, blocks: prose });
  return out;
}
