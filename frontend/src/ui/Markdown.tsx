import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** 全站唯一的 Markdown 排版（聊天文字块、项目档案共用），样式在 blocks.css 的 .blk-text。 */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="blk-text">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
