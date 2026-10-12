/** 本机斜杠命令的执行（v1.87，规则在 lib/slash.ts），和 App 的 slash_actions.dart 同一套：不发消息、不花 token，全部复用已有入口——
 *  /new → useChat.open(null)；/compact → POST …/compact（同 ConversationMemory、同一句 compactToast）；
 *  /plan → useChat.setPlanMode（接了话 = 打开后发出去）；/copy → 最近一条助手回答的 copyText；/status → 标题的本对话用量面板。
 *  /model → 不接话回一句“现在用 X；可选…”，接名字 findModel 认出来就 setModel（同模型钮一条 dirty/PATCH 路）；
 *  /diff → latestChanges 找最近一张改动卡 → seek（搜索定位同一条路：滚过去 + 闪一下）。
 *  返回给输入框下方显示的一句提示（没有就 undefined）。 */
import { http } from "../../lib/api";
import { compactToast, type CompactResult, type ConversationContext } from "../../lib/conversationContext";
import { latestChanges, latestChangesNote, NO_CHANGES } from "../../lib/changes";
import { effectiveModel, findModel, findModelMiss, modelListNote, modelNote, toChoice, type ModelCatalog } from "../../lib/models";
import { lastReplyText, type SlashCall } from "../../lib/slash";
import type { Message, OutgoingFile } from "../../lib/types";

export const NO_CONVERSATION = "还没开始对话";
export const planModeNote = (on: boolean) => (on ? "计划模式：先出方案，你批准后再动手" : "已退出计划模式");

export type SlashDeps = {
  activeId: string | null; messages: Message[]; planMode: boolean;
  open: (id: string | null) => unknown; setPlanMode: (on: boolean) => Promise<void>;
  send: (t: string, files?: OutgoingFile[]) => void; showStatus: () => void;
  catalog: ModelCatalog | null; model: string | null; setModel: (choice: string | null) => unknown; seek: (messageId: string) => void;
};

export async function runSlash(call: SlashCall, files: OutgoingFile[], d: SlashDeps): Promise<string | undefined> {
  switch (call.command.name) {
    case "new": await d.open(null); return;
    case "plan": {
      const withText = !!call.args || files.length > 0;
      const on = withText ? true : !d.planMode;
      await d.setPlanMode(on);
      if (withText) { d.send(call.args, files); return; }
      return on !== d.planMode ? planModeNote(on) : undefined;
    }
    case "copy": {
      const t = lastReplyText(d.messages);
      if (!t) return "还没有可复制的回答";
      try { await navigator.clipboard.writeText(t); return "已复制上一条回答"; } catch { return "浏览器不让写剪贴板"; }
    }
    case "status":
      if (!d.activeId) return NO_CONVERSATION;
      d.showStatus();
      return;
    case "model": {
      const cat = d.catalog;
      if (!cat || cat.models.length < 2) return "服务器只配了一个模型";
      if (!call.args) return modelListNote(cat, d.model);
      const id = findModel(cat, call.args);
      if (!id) return findModelMiss(cat, call.args);
      if (id !== effectiveModel(cat, d.model)?.id) await d.setModel(toChoice(cat, id));
      return modelNote(cat, id);
    }
    case "diff": {
      const hit = latestChanges(d.messages);
      if (!hit) return NO_CHANGES;
      d.seek(hit[0]);
      return latestChangesNote(hit[1]);
    }
    case "compact": {
      const id = d.activeId;
      if (!id) return NO_CONVERSATION;
      try {
        const before = await http.get<ConversationContext>(`/api/conversations/${id}/context`);
        const r = await http.post<CompactResult>(`/api/conversations/${id}/compact`, {});
        return compactToast(before, r);
      } catch (e) { return e instanceof Error ? e.message : "整理失败，稍后再试"; }
    }
  }
}
