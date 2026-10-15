import { useCallback, useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import { conversationMarkdown, downloadText, exportFileName } from "../lib/export";
import { SEARCH_DEBOUNCE_MS } from "../lib/history";
import type { ConversationSummary, Message } from "../lib/types";
import { noticeDialog } from "../ui/dialog";

/**
 * 对话列表的唯一归属地：加载、搜索（防抖 + 丢弃过期响应）、置顶、改名、删除。
 * useChat 组合它，界面只读 items / query。
 * v2.95 项目 = 一段对话：projectId 有值时列表 = 这个项目的那段对话（GET /api/conversations?project_id=，≤1 项，服务器没有就建），
 * 不搜索（服务器已删项目内搜索）、不删除（项目对话随项目删除，服务器回 409）。
 */
export function useConversations(projectId?: string) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const seq = useRef(0);
  const queryRef = useRef(query);
  queryRef.current = query;

  /** 返回这次拉到的列表（过期响应返回 null）：项目范围用它拿到那段对话的 id。 */
  const load = useCallback(async (q: string): Promise<ConversationSummary[] | null> => {
    const mine = ++seq.current;
    const term = projectId ? "" : q.trim();
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (term) params.set("q", term);
    const qs = params.toString();
    setSearching(!!term);
    try {
      const list = await http.get<ConversationSummary[]>(`/api/conversations${qs ? `?${qs}` : ""}`);
      if (mine !== seq.current) return null;   // 慢的旧请求不覆盖新结果
      setItems(list);
      return list;
    } finally {
      if (mine === seq.current) setSearching(false);
    }
  }, [projectId]);

  const refresh = useCallback(() => load(queryRef.current), [load]);

  // 输入停顿后再搜；清空立即恢复完整列表
  useEffect(() => {
    if (projectId || !query.trim()) { load("").catch(() => {}); return; }
    const t = setTimeout(() => { load(query).catch(() => {}); }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query, load, projectId]);

  /** 乐观更新后同步服务端；失败就以服务端为准重新拉。 */
  const patch = useCallback(async (id: string, body: { title?: string; pinned?: boolean; model?: string; reasoning?: string; mode?: string }) => {
    setItems((xs) => xs.map((c) => (c.id === id ? { ...c, ...body } : c)));
    try { await http.patch(`/api/conversations/${id}`, body); }
    finally { refresh(); }
  }, [refresh]);

  const rename = useCallback((id: string, title: string) => {
    const t = title.trim();
    return t ? patch(id, { title: t }) : Promise.resolve();
  }, [patch]);
  const setPinned = useCallback((id: string, pinned: boolean) => patch(id, { pinned }), [patch]);
  /** 换对话的模型；null = 回默认（发 ""）。失败会抛出，useChat 据此把选择留到下一条消息带上。 */
  /** 模型选择（模型 + 思考强度）一起 PATCH；null = 回默认。 */
  const setChoice = useCallback((id: string, model: string | null, reasoning: string | null, plan = false) =>
    patch(id, { model: model ?? "", reasoning: reasoning ?? "", mode: plan ? "plan" : "default" }), [patch]);

  const remove = useCallback(async (id: string) => {
    setItems((xs) => xs.filter((c) => c.id !== id));
    try {
      await http.del(`/api/conversations/${id}`);
    } catch (e) {  // 409：定时任务这次还在往这段对话里写（搜索里能点到运行对话）；项目对话随项目删除
      void noticeDialog("删不了", e instanceof Error ? e.message : String(e));
    }
    refresh();
  }, [refresh]);

  /** 导出整段对话为 Markdown 文件（以服务器为准，正在打开的对话也重新拉）。 */
  const exportMarkdown = useCallback(async (c: ConversationSummary) => {
    try {
      const { messages } = await http.get<{ messages: Message[] }>(`/api/conversations/${c.id}`);
      downloadText(exportFileName(c.title), conversationMarkdown(c.title, messages));
    } catch (e) {
      void noticeDialog("导出失败", e instanceof Error ? e.message : String(e));
    }
  }, []);

  /** 服务器自动起的标题（conversation.title 事件）：本地原地换字，不发请求。 */
  const retitle = useCallback((id: string, title: string) => {
    setItems((xs) => xs.map((c) => (c.id === id ? { ...c, title } : c)));
  }, []);
  return { items, query, setQuery, searching, refresh, retitle, rename, setPinned, setChoice, remove, exportMarkdown };
}

export type Conversations = ReturnType<typeof useConversations>;
