import type { TextBlock as T } from "../lib/types";
import Markdown from "../ui/Markdown";

export default function TextBlock({ block }: { block: T }) {
  return <Markdown text={block.text} />;
}
