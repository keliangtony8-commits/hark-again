import { useCallback, useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import { memoryStore } from "../lib/memoryStore";
import { OUTBOX_GIVE_UP_MS, outbox } from "../lib/outbox";
import { STEER_STATUS, beforePending, isSteer } from "../lib/steer";
import { ChatSocket, type LinkStatus } from "../lib/socket";
import type { Block, FileBlock, Message, OutgoingFile, ServerEvent, TextBlock } from "../lib/types";
import { mergeStep, stepFromStatus } from "../lib/activity";
import { mergeRetry, RETRY_CLEARS_ON, retryNotice } from "../lib/retry";
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
 *   思考强度 effort（null = 模型默认）和模型是同一份“模型选择”：同一个 dirty、一起 PATCH / 一起随消息带上。
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
  const [effort, setEffortState] = useState<string | null>(null);
  /** 选了“自动”时这一轮 / 上一轮服务器实际用的别名（turn.model、详情 routed_model）；模型钮显示“自动 · 快速”。 */
  const [routed, setRouted] = useState<string | null>(null);
  const effortRef = useRef(effort);
  effortRef.current = effort;
  /** 计划模式（v1.71，后端 app/plan_mode.py）：只看不改，先交方案给你批准。和模型同属“模型选择”，同一个 dirty。 */
  const [planMode, setPlanModeState] = useState(false);
  const planRef = useRef(planMode);
  planRef.current = planMode;
  const modelDirty = useRef(false); // 本机改了模型 / 思考强度还没送到服务器（新对话 / PATCH 没成功）
  /** 改过还没送到的模型选择，随消息带上。 */
  const modelField = () => (modelDirty.current
    ? { model: modelRef.current ?? "", reasoning: effortRef.current ?? "", mode: planRef.current ? "plan" : "default" } : {});
  const socket = useRef<ChatSocket>();
  const giveUp = useRef<ReturnType<typeof setTimeout>>();
  const started = useRef(false);   // 在飞的这条已收到 message.start
  const resync = useRef(false);    // 断线丢了中途的事件，连上后要重新拉当前对话
  const regenerating = useRef(false); // 在飞的这一轮是重新生成（用户消息早已在服务器上）
  // 续传（v1.61，服务器 live_turns；同 App chat_controller）：回答不绑在连接上，断线不丢半截，连上后 turn.resume 按 seq 接着收
  const turnId = useRef<string | null>(null);   // 在看的这一轮（老服务器没有）
  const turnConv = useRef<string | null>(null);
  const turnSeq = useRef(0);                    // 收到的最后一个事件编号
  const reattach = useRef(false);               // 回复中途断线、服务器支持续传：连上后续传
  const probe = useRef<string | null>(null);    // 发出后回复前断线的那个对话：连上后问服务器是否已在答
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
      const { messages, model: m, reasoning: r, routed_model: rm, mode: md } = await http.get<{ messages: Message[]; model?: string | null; reasoning?: string | null; routed_model?: string | null; mode?: string | null }>(`/api/conversations/${id}`);
      if (seq === openSeq.current && threadRef.current.id === id && !modelDirty.current) { setModelState(m ?? null); setEffortState(r ?? null); setPlanModeState(md === "plan"); }
      if (seq === openSeq.current && threadRef.current.id === id) setRouted(rm ?? null);
      if (seq !== openSeq.current || threadRef.current.id !== id || streamingRef.current) return;
      setThread((t) => ({ id, messages: [...messages, ...t.messages.filter(isUnsent)] }));
    } catch (e) {
      if (seq === openSeq.current && threadRef.current.id === id) setError((e as Error).message);
    }
  }, []);

  /** 问服务器这个对话有没有正在写的回答（别的设备 / 断线前发起的），有就接着看。 */
  const watch = (id: string) => socket.current?.send({ type: "turn.resume", conversation_id: id });

  const onEvent = (e: ServerEvent) => {
    // 续传去重：同一轮里编号不大于已收到的，是重连补发的重复；turn.resumed 是答复不是事件，不参与
    if (e.turn_id && typeof e.seq === "number" && e.turn_id === turnId.current && e.type !== "turn.resumed") {
      if (e.seq <= turnSeq.current) return;
      if (e.type !== "turn.snapshot") turnSeq.current = e.seq;
    }
    // 模型又开始产出：普通重试的提示收起（换备用模型的提示留到这一轮结束）
    if (RETRY_CLEARS_ON.has(e.type)) patchPending((p) => (p.retry && !p.retry.fallback ? { ...p, retry: undefined } : p));
    switch (e.type) {
      case "message.start": {
        const cur = threadRef.current.id;
        if (cur && cur !== e.conversation_id) return;   // 别的对话的事件
        started.current = true;
        if (e.turn_id && e.turn_id !== turnId.current) { turnId.current = e.turn_id; turnSeq.current = e.seq ?? 0; }
        turnConv.current = e.conversation_id;
        if (!cur) outbox.save(projectId, null, []);       // 新对话有了 id，剩下的未发消息随它搬家
        const um = e.user_message;   // 编辑：服务器规整后的版本覆盖本地乐观改写（保留本地 id）
        const replaced = new Set(e.replaced ?? []);   // 旁观别处发起的重新生成：撤掉被替换的旧回复
        setStreaming(true);
        setThread((t) => {
          const ms = t.messages.filter((x) => !x.pending && !replaced.has(x.id));
          // 想插进上一轮却排成了新一轮的那句（client_id）：挪到末尾、不再标补充
          const k = e.client_id ? ms.findIndex((x) => x.id === e.client_id) : -1;
          if (k >= 0) { const [m] = ms.splice(k, 1); ms.push({ ...m, status: undefined, outbox: undefined }); }
          const i = ms.map((x) => x.role).lastIndexOf("user");
          if (um && i >= 0) ms[i] = { ...ms[i], blocks: um.blocks };
          return { id: e.conversation_id, messages: [...ms, { id: "pending", role: "assistant", blocks: [], steps: [], pending: true }] };
        });
        break;
      }
      case "turn.steered": {
        const cur = threadRef.current.id;
        if (cur && e.conversation_id && cur !== e.conversation_id) return;
        setMessages((ms) => {
          const k = e.client_id ? ms.findIndex((x) => x.id === e.client_id) : -1;
          if (k >= 0) return ms.map((x, j) => (j === k ? { ...x, status: STEER_STATUS, outbox: undefined } : x));   // 本机发的：认领
          return ms.some((x) => x.id === e.message.id) ? ms : beforePending(ms, e.message);   // 别的设备补充的
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
      case "turn.model":   // 选了“自动”：服务器这一轮挑的模型（v1.70 model_router）
        if (e.model) setRouted(e.model);
        break;
      case "turn.retry": {
        const n = retryNotice(e);
        patchPending((p) => ({ ...p, retry: mergeRetry(p.retry, n) }));
        break;
      }
      case "thinking.delta":
        patchPending((p) => { const now = Date.now(); return { ...p, thought: keepTail((p.thought ?? "") + e.text), thinkFrom: p.thinkFrom ?? now, thinkTo: now }; });
        break;
      case "tool.status": {
        const step = stepFromStatus(e);
        patchPending((p) => ({ ...p, steps: mergeStep(p.steps ?? [], step) }));
        break;
      }
      case "turn.resumed":
        onResumed(e);
        break;
      case "turn.snapshot": {
        const cur = threadRef.current.id;
        if (cur && e.conversation_id && cur !== e.conversation_id) return;
        turnId.current = e.turn_id; turnSeq.current = e.seq; started.current = true;
        setStreaming(true);
        setMessages((ms) => {
          const prev = ms.find((x) => x.pending);
          const p: Message = { id: "pending", role: "assistant", blocks: e.message.blocks ?? [], steps: e.message.steps ?? [], pending: true,
            thought: prev?.thought, thinkFrom: prev?.thinkFrom, thinkTo: prev?.thinkTo };
          // 途中补充以快照为准：本机未认领的乐观气泡撤掉，服务器收下的按 id 补上
          const kept = ms.filter((x) => !x.pending && !(isSteer(x) && x.id.startsWith("local-")));
          const extra = (e.steered ?? []).filter((m) => !kept.some((x) => x.id === m.id));
          return [...kept, ...extra, p];
        });
        break;
      }
      case "message.done":
        regenerating.current = false;
        reattach.current = false;
        // 本机才有的思考（内容 + 计时）接到正式消息上：回复上方能展开“已思考 N 秒”
        setMessages((m) => {
          const p = m.find((x) => x.pending);
          const done = p?.thought ? { ...e.message, thought: p.thought, thinkFrom: p.thinkFrom, thinkTo: p.thinkTo } : e.message;
          return [...m.filter((x) => !x.pending), done];
        });
        setStreaming(false);   // flush effect 随后送出期间点了“重发”的那条
        list.refresh();
        break;
      case "conversation.mode":
        // 方案被批准、服务器已退出计划模式（v1.71）：“计划”钮关掉，列表同步
        if (e.conversation_id === threadRef.current.id && !modelDirty.current) setPlanModeState(e.mode === "plan");
        list.refresh();
        break;
      case "conversation.title":
        // 第一轮回复后服务器在后台起好了短标题：列表和顶栏原地换字，再同步一次
        if (e.title) { list.retitle(e.conversation_id, e.title); list.refresh(); }
        break;
      case "message.stopped":
        // 还没吐字就停了：撤掉思考占位；用户消息留着（服务器上也在），可以“重试”
        regenerating.current = false;
        reattach.current = false;
        setMessages((m) => m.filter((x) => !x.pending));
        setStreaming(false);
        list.refresh();
        break;
      case "error": {
        // 重新生成被拒（另一台设备已接着聊）或没跑完：本地撤掉的旧回复可能还在服务器上
        const id = threadRef.current.id;
        if (regenerating.current && id) { streamingRef.current = false; fetchThread(id, openSeq.current); }
        regenerating.current = false;
        reattach.current = false;
        setMessages((m) => m.filter((x) => !(x.pending && x.blocks.length === 0)).map((x) => ({ ...x, pending: false })));
        setError(e.message);
        setStreaming(false);
        break;
      }
    }
  };

  const onResumed = (e: Extract<ServerEvent, { type: "turn.resumed" }>) => {
    const cur = threadRef.current.id;
    if (e.conversation_id && cur && e.conversation_id !== cur) return;
    const probed = !!probe.current && probe.current === e.conversation_id;
    probe.current = null;
    if (!e.live) {
      if (reattach.current) {
        // 服务器没这轮了（重启 / 断太久）：丢掉半截，以服务器落库的为准
        reattach.current = false;
        setMessages((ms) => ms.filter((x) => !x.pending));
        streamingRef.current = false;
        setStreaming(false);
        if (cur) fetchThread(cur, openSeq.current);
      } else if (probed && cur && !streamingRef.current) fetchThread(cur, openSeq.current);
      return;
    }
    reattach.current = false;
    if (e.turn_id !== turnId.current) { turnId.current = e.turn_id; turnSeq.current = 0; started.current = false; }
    turnConv.current = e.conversation_id ?? turnConv.current;
    if (!streamingRef.current) {
      // 接上正在写的回答：发送失败的那条其实已经送到了
      if (probed) setMessages((ms) => {
        const i = ms.length - 1;
        return i >= 0 && ms[i].role === "user" && ms[i].outbox === "failed" ? [...ms.slice(0, i), { ...ms[i], outbox: undefined }] : ms;
      });
      streamingRef.current = true;
      setStreaming(true);
    }
  };

  const onStatus = (s: LinkStatus) => {
    setLink(s);
    if (s === "down" && streamingRef.current && started.current && turnId.current) {
      reattach.current = true;   // 服务器支持续传：回答在那边接着写，这里什么都不丢
    } else if (s === "down" && streamingRef.current) {
      // 回复还没开始：服务器可能没收到，最后一条用户消息标失败让用户决定；已经开始：丢掉半截，连上后从服务器拿完整的
      setMessages((ms) => {
        const out = ms.filter((x) => !x.pending);
        if (!started.current && !regenerating.current) {
          const i = out.map((x) => x.role).lastIndexOf("user");
          if (i >= 0) out[i] = { ...out[i], outbox: "failed" };
          probe.current = threadRef.current.id;
        }
        return out;
      });
      resync.current = started.current || regenerating.current;
      regenerating.current = false;
      setStreaming(false);
    } else if (s === "open") {
      const id = threadRef.current.id;
      if (reattach.current && turnId.current) {
        socket.current?.send({ type: "turn.resume", turn_id: turnId.current, conversation_id: turnConv.current ?? id, after: turnSeq.current });
      } else if (id && !streamingRef.current) watch(id);
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
      client_id: m.id,
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
    reattach.current = false;
    probe.current = null;
    const summary = list.items.find((c) => c.id === id);
    setModelState(summary?.model ?? null);
    setEffortState(summary?.reasoning ?? null);
    setRouted(summary?.routed_model ?? null);
    setPlanModeState(summary?.mode === "plan");
    const restored = outbox.load(projectId, id);
    if (!id) { setThread({ id: null, messages: restored }); return; }
    try {
      const { messages, model: m, reasoning: r, routed_model: rm, mode: md } = await http.get<{ messages: Message[]; model?: string | null; reasoning?: string | null; routed_model?: string | null; mode?: string | null }>(`/api/conversations/${id}`);
      if (seq !== openSeq.current) return;
      if (!modelDirty.current) { setModelState(m ?? null); setEffortState(r ?? null); setPlanModeState(md === "plan"); }
      setRouted(rm ?? null);
      setThread({ id, messages: [...messages, ...restored] });
      if (!streamingRef.current) watch(id);
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

  /** 生成中能不能补一句给这一轮（服务器 steering；新对话的第一轮还没有 id 时不行）。 */
  const canSteer = streaming && !stopping && !!thread.id;

  const send = useCallback((text: string, files: OutgoingFile[] = []) => {
    if (!text.trim() && files.length === 0) return;
    if (busy) {
      if (!canSteer || files.length > 0 || !text.trim()) return;
      // 途中补充：立刻插在生成中那条前面；线不通就标失败（“重发”= 挪到末尾排成下一轮）
      const id = `local-${crypto.randomUUID()}`;
      const ok = link === "open" && !!socket.current?.send({
        type: "user.message", conversation_id: thread.id, project_id: projectId, text: text.trim(), steer: true, client_id: id,
      });
      setError(null);
      const m: Message = { id, role: "user", blocks: [{ type: "text", text: text.trim() }], created_at: new Date().toISOString(),
        ...(ok ? { status: STEER_STATUS } : { outbox: "failed" as const }) };
      setMessages((ms) => beforePending(ms, m));
      return;
    }
    setError(null);
    const blocks: Block[] = [
      ...(text.trim() ? [{ type: "text" as const, text: text.trim() }] : []),
      ...files.map(asFileBlock),
    ];
    setMessages((m) => [...m, { id: `local-${crypto.randomUUID()}`, role: "user", blocks, outbox: "queued", created_at: new Date().toISOString() }]);
  }, [busy, canSteer, link, thread.id, projectId]);

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
  const replyApproval = useCallback((id: string, approved: boolean, option?: string) => {
    if (!socket.current?.send({ type: "approval.reply", id, approved, ...(option ? { option } : {}) })) setError("连接已断开，连上后再点一次");
  }, []);

  /** 表单卡（登录、验证码）的答复，同样实时、不排队。值只走这一条线，不进本地状态。 */
  const replyForm = useCallback((id: string, values: Record<string, string> | null, remember: boolean) => {
    const ok = !!socket.current?.send({ type: "form.reply", id, values, remember });
    if (!ok) setError("连接已断开，连上后再点一次");
    return ok;
  }, []);

  /** 换这个对话的模型（null = 默认）。界面立刻变；服务器那边见文件头“模型”。 */
  const pushChoice = useCallback(async () => {
    modelDirty.current = true;
    const id = threadRef.current.id;
    if (!id) return;   // 新对话：随第一条消息带上
    const [m, e, pl] = [modelRef.current, effortRef.current, planRef.current];
    try {
      await list.setChoice(id, m, e, pl);
      if (threadRef.current.id === id && modelRef.current === m && effortRef.current === e && planRef.current === pl) modelDirty.current = false;
    } catch { /* 断网等：随下一条消息带过去 */ }
  }, [list.setChoice]);
  const setModel = useCallback(async (choice: string | null) => {
    if (choice === modelRef.current) return;
    setModelState(choice);
    modelRef.current = choice;
    await pushChoice();
  }, [pushChoice]);
  /** 换这个对话的思考强度（null = 模型默认）。和模型同一条路。 */
  const setEffort = useCallback(async (choice: string | null) => {
    if (choice === effortRef.current) return;
    setEffortState(choice);
    effortRef.current = choice;
    await pushChoice();
  }, [pushChoice]);

  /** 开 / 关计划模式。和模型同一条路；这一轮正在跑时从下一轮起生效。 */
  const setPlanMode = useCallback(async (on: boolean) => {
    if (on === planRef.current) return;
    setPlanModeState(on);
    planRef.current = on;
    await pushChoice();
  }, [pushChoice]);

  const reconnect = useCallback(() => socket.current?.reconnectNow(), []);

  /** 服务器在当前对话里自己说了话（后台任务结束后接着说的一轮）：静默拿一次服务器版本；正在生成时不打断。 */
  const refreshActive = useCallback(() => {
    const id = threadRef.current.id;
    if (id && !streamingRef.current) void fetchThread(id, openSeq.current);
  }, [fetchThread]);

  /** 改动卡的整轮撤销（v1.68，后端 turn_changes.py）：找到带这个 token 的回复，POST 撤销，成功后换成服务器回的版本。 */
  const undoChanges = useCallback(async (token: string): Promise<string | null> => {
    const cid = threadRef.current.id;
    const m = threadRef.current.messages.find((x) => x.blocks.some((b) => b.type === "changes" && b.token === token));
    if (!cid || !m) return "找不到这条回复";
    try {
      const next = await http.post<Message>(`/api/conversations/${cid}/messages/${m.id}/changes/undo`, {});
      setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...next, thought: x.thought, thinkFrom: x.thinkFrom, thinkTo: x.thinkTo } : x)));
      return null;
    } catch (e) {
      return e instanceof Error && e.message ? e.message : "没撤销成功，稍后再试";
    }
  }, []);

  /** 定位到当前对话里的某条消息（/diff 跳到改动卡，v1.89）：和搜索命中同一条 focus 路。 */
  const seek = useCallback((id: string) => { if (thread.messages.some((m) => m.id === id)) setFocus(id); }, [thread.messages]);

  return {
    refreshActive, undoChanges, seek,
    list, activeId: thread.id, messages: thread.messages, streaming, busy, error, link,
    canRegenerate, canStop, canSteer, editableId, focus, model, routed, setModel, effort, setEffort, planMode, setPlanMode, takeFocus: useCallback(() => setFocus(null), []), open, send, stop, resend, discard, regenerate, edit, remove, replyApproval, replyForm, reconnect,
  };
}

export type Chat = ReturnType<typeof useChat>;

/** 上传附件和项目文件引用分开发（attachments / project_files）。 */
const fileIds = (blocks: Block[], source: FileBlock["source"]) =>
  blocks.flatMap((b) => (b.type === "file" && b.source === source ? [b.id] : []));
