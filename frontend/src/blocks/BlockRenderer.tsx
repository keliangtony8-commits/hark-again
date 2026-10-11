import type { ComponentType } from "react";
import type { Block } from "../lib/types";
import { registry } from "./registry";
import "./blocks.css";

export default function BlockRenderer({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        const C = registry[b.type] as ComponentType<{ block: Block }> | undefined;
        return C ? <C key={i} block={b} /> : null;
      })}
    </>
  );
}
