import { useCallback, useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import { memoryStore } from "../lib/memoryStore";
import { OUTBOX_GIVE_UP_MS, outbox } from "../lib/outbox";
import { ChatSocket, type LinkStatus } from "../lib/socket";
import type { Block, FileBlock, Message, OutgoingFile, ServerEvent, TextBlock } from "../lib/types";
import { asFileBlock } from "../lib/files";
import { useConversations } from "./useConversations";

/** 眼前这段对话：id 和消息总是一起换，持久化发件箱时才不会把 A 的消息写进 B。 */
type Thread = { id: string | null; messages: Message[] };

const isUnsent = (m: Message) => !!m.outbox;
/** 思考可能有几万字，界面只看最近的：只留尾部（与 App Message.thoughtKeep 相同）。 */
export const THOUGHT_KEEP = 2000;
const keepTail = (t: string) => (t.length > THOUGHT_KEEP ? t.slice(-THOUGHT_KEEP) : t);
const plainText = (blocks: Block[]) => blocks.map((b) => (b.type === "text" ? b.text : "")).join("\n").trim();

/**
 * 聊天状态的唯一归属地（对应 App 的 chat_controller）。projectId 为空 = 主聊天；有值 = 该项目内的聊天。
 * 发件箱：发出的消息先以 outbox="queued" 进列表；线通了才真正写出，一次只在飞一条（flush effect 一处负责）。
 *   等 45 秒没连上 → failed；发出后、回复开始前断线 → failed（服务器可能没收到）；回复中途断线 → 连上后从服务器重新拉。
 *   failed 由用户 resend()（挪到末尾重新排队）或 discard()。
 *   未发出的消息按对话存进 lib/outbox（persist effect 一处写），切走/刷新页面后以“发送失败”回来。
 * 停止：生成中 stop() 发 message.cancel，等服务器回 message.done（半截回复，status=stopped）或 message.stopped
 *   （还没吐字）再收尾——不在本地先砍，界面与服务器落库一致。stopping 期间停止键置灰防连点，一轮结束自动清掉。
 * 重新生成：只针对最后一条回复（或上一轮失败、没有回复时的“重试”）。不排队——线不通直接提示；
 *   先在本地撤掉旧回复，服务器拒绝或中途断线就重新拉对话，以服务器为准。
 * 编辑：只针对最后一条用户消息（editableId），= 带新文字的重新生成：本地先改气泡、撤掉后面的回复，
 *   message.start 带回服务器版本（user_message）再覆盖；附件保留，本地 id 不变。
 * 定位：搜索命中正文时 open(id, 消息 id)。focus 是一次性请求，ChatView 等那条消息渲染出来就滚过去、闪一下并 takeFocus()；
 *   服务器版本里没有这条（已被删/重新生成）就静默作废。
 * 模型：model = 这个对话选的别名（null = 默认），打开时先取列表里的、再以服务器详情为准。setModel() 先改本地；
 *   已有对话立刻 PATCH，没成功或还是新对话就记 modelDirty，随下一条 user.message / message.regenerate 带上
 *   （"" = 回默认）——所以“切到深度再点重新生成”= 换模型重答。与 App chat_controller 同规则。
 */
export function useChat(projectId?: string) {
  const list = useConversations(projectId);
  const [thread, setThread] = useState<Thread>(() => ({ id: null, messages: outbox.load(projectId, null) }));
  const [streaming, setStreaming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<LinkStatus>("connecting");
  const [focus, setFocus] = useState<string | null>(null);
  const [model, setModelState] = useState<string | null>(null);
  const modelRef = useRef(model);
  modelRef.current = model;
  const modelDirty = useRef(false); // 本机改了模型还没送到服务器（新对话 / PATCH 没成功）
  /** 改过还没送到的模型选择，随消息带上。 */
  const modelField = () => (modelDirty.current ? { model: modelRef.current ?? "" } : {});
  const socket = useRef<ChatSocket>();
  const giveUp = useRef<ReturnType<typeof setTimeout>>();
  const started = useRef(false);   // 在飞的这条已收到 message.start
  const resync = useRef(false);    // 断线丢了中途的事件，连上后要重新拉当前对话
  const regenerating = useRef(false); // 在飞的这一轮是重新生成（用户消息早已在服务器上）
  const openSeq = useRef(0);       // 快速连点切换对话时，只认最后一次 open
  const threadRef = useRef(thread);
  threadRef.current = thread;
  const streamingRef = useRef(streaming);
  streamingRef.current = streaming;

  const setMessages = (fn: (ms: Message[]) => Message[]) => setThread((t) => ({ ...t, messages: fn(t.messages) }));
  const clearGiveUp = () => { clearTimeout(giveUp.current); giveUp.current = undefined; };

  /** 只改正在生成的那条消息。 */
  const patchPending = (fn: (m: Message) => Message) =>
    setMessages((ms) => {
      const last = ms[ms.length - 1];
      return last?.pending ? [...ms.slice(0, -1), fn(last)] : ms;
    });

  /** 拉服务器版本；本机还没发出的消息接在后面，不能被刷新冲掉。 */
  const fetchThread = useCallback(async (id: string, seq: number) => {
    try {
      const { messages, model: m } = await http.get<{ messages: Message[]; model?: string | null }>(`/api/conversations/${id}`);
      if (seq === openSeq.current && threadRef.current.id === id && !modelDirty.current) setModelState(m ?? null);
      if (seq !== openSeq.current || threadRef.current.id !== id || streamingRef.current) return;
      setThread((t) => ({ id, messages: [...messages, ...t.messages.filter(isUnsent)] }));
    } catch (e) {
      if (seq === openSeq.current && threadRef.current.id === id) setError((e as Error).message);
    }
  }, []);

  const onEvent = (e: ServerEvent) => {
    switch (e.type) {
      case "message.start": {
        const cur = threadRef.current.id;
        if (cur && cur !== e.conversation_id) return;   // 别的对话的事件
        started.current = true;
        if (!cur) outbox.save(projectId, null, []);       // 新对话有了 id，剩下的未发消息随它搬家
        const um = e.user_message;   // 编辑：服务器规整后的版本覆盖本地乐观改写（保留本地 id）
        setThread((t) => {
          const ms = [...t.messages];
          const i = ms.map((x) => x.role).lastIndexOf("user");
          if (um && i >= 0) ms[i] = { ...ms[i], blocks: um.blocks };
          return { id: e.conversation_id, messages: [...ms, { id: "pending", role: "assistant", blocks: [], tools: [], pending: true }] };
        });
        break;
      }
      case "block.start":
      case "block.update":
        patchPending((p) => { const blocks = [...p.blocks]; blocks[e.index] = e.block; return { ...p, blocks }; });
        if (e.block.type === "memory") memoryStore.invalidate(); // 助手改了记忆：记忆页和记忆卡共用的列表重拉
        break;
      case "block.delta":
        patchPending((p) => {
          const blocks = [...p.blocks];
          const b = blocks[e.index] as TextBlock | undefined;
          blocks[e.index] = { type: "text", text: (b?.text ?? "") + e.text };
          return { ...p, blocks };
        });
        break;
      case "thinking.delta":
        patchPending((p) => { const now = Date.now(); return { ...p, thought: keepTail((p.thought ?? "") + e.text), thinkFrom: p.thinkFrom ?? now, thinkTo: now }; });
        break;
      case "tool.status": {
        const { type: _t, ...run } = e;
        patchPending((p) => {
          const tools = p.tools ?? [];
          const i = tools.findIndex((t) => t.id === run.id);
          return { ...p, tools: i < 0 ? [...tools, run] : tools.map((t, j) => (j === i ? run : t)) };
        });
        break;
      }
      case "message.done":
        regenerating.current = false;
        // 本机才有的思考（内容 + 计时）接到正式消息上：回复上方能展开“已思考 N 秒”
        setMessages((m) => {
          const p = m.find((x) => x.pending);
          const done = p?.thought ? { ...e.message, thought: p.thought, thinkFrom: p.thinkFrom, thinkTo: p.thinkTo } : e.message;
          return [...m.filter((x) => !x.pending), done];
        });
        setStreaming(false);   // flush effect 随后送出期间点了“重发”的那条
        list.refresh();
        break;
      case "message.stopped":
        // 还没吐字就停了：撤掉思考占位；用户消息留着（服务器上也在），可以“重试”
        regenerating.current = false;
        setMessages((m) => m.filter((x) => !x.pending));
        setStreaming(false);
        list.refresh();
        break;
      case "error": {
        // 重新生成被拒（另一台设备已接着聊）或没跑完：本地撤掉的旧回复可能还在服务器上
        const id = threadRef.current.id;
        if (regenerating.current && id) { streamingRef.current = false; fetchThread(id, openSeq.current); }
        regenerating.current = false;
        setMessages((m) => m.filter((x) => !(x.pending && x.blocks.length === 0)).map((x) => ({ ...x, pending: false })));
        setError(e.message);
        setStreaming(false);
        break;
      }
    }
  };

  const onStatus = (s: LinkStatus) => {
    setLink(s);
    if (s === "down" && streamingRef.current) {
      // 回复还没开始：服务器可能没收到，最后一条用户消息标失败让用户决定；已经开始：丢掉半截，连上后从服务器拿完整的
      setMessages((ms) => {
        const out = ms.filter((x) => !x.pending);
        if (!started.current && !regenerating.current) {
          const i = out.map((x) => x.role).lastIndexOf("user");
          if (i >= 0) out[i] = { ...out[i], outbox: "failed" };
        }
        return out;
      });
      resync.current = started.current || regenerating.current;
      regenerating.current = false;
      setStreaming(false);
    } else if (s === "open") {
      const id = threadRef.current.id;
      if (resync.current && id) fetchThread(id, openSeq.current);
      resync.current = false;
    }
  };

  // 长连接只建一次；事件处理走 ref 拿最新闭包
  const handlers = useRef({ onEvent, onStatus });
  handlers.current = { onEvent, onStatus };
  useEffect(() => {
    const s = new ChatSocket((e) => handlers.current.onEvent(e), (st) => handlers.current.onStatus(st));
    socket.current = s;
    setLink(s.status);
    return () => { s.close(); clearGiveUp(); };
  }, []);

  // flush：把排在最前的待发送消息交给长连接；线不通就启动放弃计时。唯一的写出点
  useEffect(() => {
    if (streaming) return;
    const m = thread.messages.find((x) => x.outbox === "queued");
    if (!m) { clearGiveUp(); return; }
    const ok = link === "open" && !!socket.current?.send({
      type: "user.message", conversation_id: thread.id, project_id: projectId, text: plainText(m.blocks),
      attachments: fileIds(m.blocks, "upload"),
      project_files: fileIds(m.blocks, "project"),
      ...modelField(),
    });
    if (!ok) {
      giveUp.current ??= setTimeout(() => {
        giveUp.current = undefined;
        setMessages((ms) => ms.map((x) => (x.outbox === "queued" ? { ...x, outbox: "failed" } : x)));
      }, OUTBOX_GIVE_UP_MS);
      return;
    }
    clearGiveUp();
    started.current = false;
    modelDirty.current = false;
    setStreaming(true);
    setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...x, outbox: undefined } : x)));
  }, [thread, streaming, link, projectId]);

  // persist：未发出的消息（id + 状态）一变就把这段对话的发件箱整份写掉。唯一的写入点
  const unsentSig = thread.messages.filter(isUnsent).map((m) => `${m.id}:${m.outbox}`).join(",");
  useEffect(() => {
    outbox.save(projectId, thread.id, threadRef.current.messages.filter(isUnsent));
  }, [projectId, thread.id, unsentSig]);

  useEffect(() => { if (!streaming) setStopping(false); }, [streaming]);   // 一轮结束（正常、停止、出错、断线）都清掉

  const open = useCallback(async (id: string | null, focusId?: string) => {
    const seq = ++openSeq.current;
    setError(null);
    setFocus(null);   // 拿到服务器版本、确认那条消息在，才发出定位请求
    clearGiveUp();   // 原对话没发出的消息已在发件箱里，随它一起换走
    modelDirty.current = false;
    setModelState(list.items.find((c) => c.id === id)?.model ?? null);
    const restored = outbox.load(projectId, id);
    if (!id) { setThread({ id: null, messages: restored }); return; }
    try {
      const { messages, model: m } = await http.get<{ messages: Message[]; model?: string | null }>(`/api/conversations/${id}`);
      if (seq !== openSeq.current) return;
      if (!modelDirty.current) setModelState(m ?? null);
      setThread({ id, messages: [...messages, ...restored] });
      if (focusId && messages.some((m) => m.id === focusId)) setFocus(focusId);
    } catch (e) {
      if (seq !== openSeq.current) return;
      setThread({ id, messages: restored });
      setError((e as Error).message);
    }
  }, [projectId, list.items]);

  const busy = streaming || thread.messages.some((m) => m.outbox === "queued");
  const last = thread.messages[thread.messages.length - 1];
  /** 最后一条是已落库的回复，或是已发出却没等到回复的用户消息（上一轮失败 → 重试）。 */
  const canRegenerate = !busy && !!thread.id && !!last && !last.pending && !last.outbox;

  /** 能编辑的那条：最后一条用户消息，已在服务器上，且没在生成（条件同 canRegenerate）。 */
  const lastUser = thread.messages.map((x) => x.role).lastIndexOf("user");
  const editableId = canRegenerate && lastUser >= 0 ? thread.messages[lastUser].id : null;

  /** 重新生成与编辑的共同流程：发请求 → 本地撤掉最后一条用户消息之后的回复（编辑时顺带换上新气泡）→ 等新一轮。 */
  const rewind = useCallback((edited?: Message) => {
    if (!canRegenerate || !last) return;
    const ok = link === "open" && !!socket.current?.send({
      type: "message.regenerate", conversation_id: thread.id,
      ...(last.role === "assistant" ? { message_id: last.id } : {}),
      ...(edited ? { text: plainText(edited.blocks) } : {}),
      ...modelField(),
    });
    if (!ok) { setError("连接已断开，连上后再试"); return; }
    started.current = false;
    regenerating.current = true;
    modelDirty.current = false;
    setError(null);
    setStreaming(true);
    setMessages((ms) => {
      const i = ms.map((x) => x.role).lastIndexOf("user");
      return edited ? [...ms.slice(0, i), edited] : ms.slice(0, i + 1);
    });
  }, [canRegenerate, last, link, thread.id]);

  /** 重新生成最后一条回复；最后一条是用户消息时 = 重试（不带 message_id）。 */
  const regenerate = useCallback(() => rewind(), [rewind]);

  /** 改写最后一条用户消息并重答。附件保留；文字清空且没有附件 = 不发。 */
  const edit = useCallback((text: string) => {
    const old = thread.messages.find((m) => m.id === editableId);
    if (!old) return;
    const files = old.blocks.filter((b) => b.type === "file");
    const t = text.trim();
    if (!t && files.length === 0) return;
    rewind({ ...old, blocks: [...(t ? [{ type: "text" as const, text: t }] : []), ...files] });
  }, [thread.messages, editableId, rewind]);

  /** 停止生成。不排队：线断了这一轮本来就会在服务器上停下（断线即停、半截落库），重连后同步即可。 */
  const canStop = streaming && !stopping;
  const stop = useCallback(() => {
    if (!canStop) return;
    const ok = link === "open" && !!socket.current?.send({ type: "message.cancel", conversation_id: thread.id });
    if (!ok) { setError("连接已断开，连上后再试"); return; }
    setStopping(true);
  }, [canStop, link, thread.id]);

  const send = useCallback((text: string, files: OutgoingFile[] = []) => {
    if ((!text.trim() && files.length === 0) || busy) return;
    setError(null);
    const blocks: Block[] = [
      ...(text.trim() ? [{ type: "text" as const, text: text.trim() }] : []),
      ...files.map(asFileBlock),
    ];
    setMessages((m) => [...m, { id: `local-${crypto.randomUUID()}`, role: "user", blocks, outbox: "queued", created_at: new Date().toISOString() }]);
  }, [busy]);

  /** 失败的消息重新排队：挪到末尾（回复会接在它后面），线通就发。 */
  const resend = useCallback((id: string) => {
    setError(null);
    setMessages((ms) => {
      const m = ms.find((x) => x.id === id && x.outbox === "failed");
      if (!m || ms.some((x) => x.outbox === "queued")) return ms;
      return [...ms.filter((x) => x.id !== id), { ...m, outbox: "queued" }];
    });
  }, []);

  /** 放弃一条没发出去的消息。 */
  const discard = useCallback((id: string) => setMessages((ms) => ms.filter((x) => !(x.id === id && isUnsent(x)))), []);

  const remove = useCallback(async (id: string) => {
    if (threadRef.current.id === id) open(null);
    outbox.drop(id);
    await list.remove(id);
  }, [open, list.remove]);

  /** 审批必须实时送达（服务器那一轮在等它），断线时不排队，直接提示。 */
  const replyApproval = useCallback((id: string, approved: boolean) => {
    if (!socket.current?.send({ type: "approval.reply", id, approved })) setError("连接已断开，连上后再点一次");
  }, []);

  /** 表单卡（登录、验证码）的答复，同样实时、不排队。值只走这一条线，不进本地状态。 */
  const replyForm = useCallback((id: string, values: Record<string, string> | null, remember: boolean) => {
    const ok = !!socket.current?.send({ type: "form.reply", id, values, remember });
    if (!ok) setError("连接已断开，连上后再点一次");
    return ok;
  }, []);

  /** 换这个对话的模型（null = 默认）。界面立刻变；服务器那边见文件头“模型”。 */
  const setModel = useCallback(async (choice: string | null) => {
    if (choice === modelRef.current) return;
    setModelState(choice);
    modelDirty.current = true;
    const id = threadRef.current.id;
    if (!id) return;   // 新对话：随第一条消息带上
    try {
      await list.setModel(id, choice);
      if (threadRef.current.id === id && modelRef.current === choice) modelDirty.current = false;
    } catch { /* 断网等：随下一条消息带过去 */ }
  }, [list.setModel]);

  const reconnect = useCallback(() => socket.current?.reconnectNow(), []);

  /** 服务器在当前对话里自己说了话（后台任务结束后接着说的一轮）：静默拿一次服务器版本；正在生成时不打断。 */
  const refreshActive = useCallback(() => {
    const id = threadRef.current.id;
    if (id && !streamingRef.current) void fetchThread(id, openSeq.current);
  }, [fetchThread]);

  return {
    refreshActive,
    list, activeId: thread.id, messages: thread.messages, streaming, busy, error, link,
    canRegenerate, canStop, editableId, focus, model, setModel, takeFocus: useCallback(() => setFocus(null), []), open, send, stop, resend, discard, regenerate, edit, remove, replyApproval, replyForm, reconnect,
  };
}

export type Chat = ReturnType<typeof useChat>;

/** 上传附件和项目文件引用分开发（attachments / project_files）。 */
const fileIds = (blocks: Block[], source: FileBlock["source"]) =>
  blocks.flatMap((b) => (b.type === "file" && b.source === source ? [b.id] : []));
