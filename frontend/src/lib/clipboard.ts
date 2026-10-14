/** 唯一的“写剪贴板”出口。navigator.clipboard 只在安全上下文（https / localhost）里有；
 *  直连 http://IP 时回落到隐藏 textarea + execCommand("copy")。都不行就抛错，调用方照旧 catch。 */
export async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    if (!document.execCommand("copy")) throw new Error("copy failed");
  } finally {
    document.body.removeChild(ta);
  }
}
