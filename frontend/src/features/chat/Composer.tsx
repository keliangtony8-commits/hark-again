import { type ReactNode, useEffect, useRef, useState } from "react";
import { workspaceFilesTitle } from "../../lib/workspace";
import { http } from "../../lib/api";
import { asFileBlock, attachSub, extOf, MAX_MESSAGE_FILES } from "../../lib/files";
import type { FileBlock, OutgoingFile, Upload } from "../../lib/types";
import ProjectFilePicker from "../projects/ProjectFilePicker";
import { useRecorder } from "../../hooks/useRecorder";
import { IconBrain, IconCheck, IconClip, IconClose, IconCopy, IconDoc, IconGauge, IconMap, IconPlus, IconEdit, IconSwap, IconFile, IconFolder, IconMic, IconSend, IconSpark, IconSplit, IconStop, IconTerminal } from "../../ui/icons";
import { shellCommandOf } from "../../lib/shell";
import { Menu } from "../../ui/kit";
import { AGENT_MENTION, MENTION_MAX, agentMatches, applyMention, mentionAt, rankMentions, rankSkills, type MentionQuery, type Sigil } from "../../lib/mentions";
import type { ProjectFile, Skill } from "../../lib/types";
import { projectFileLine } from "../projects/projectHome";
import MentionList, { type MentionItem } from "./MentionList";
import { STEER_HINT, steerable } from "../../lib/steer";
import {
  applySlash, rankSlash, slashBarText, slashBlocked, slashOf, slashQueryAt, slashSubtitle, slashToken, SLASH_COMMANDS,
  type SlashCall, type SlashIcon,
} from "../../lib/slash";
import "./chat.css";
import { uuid } from "../../lib/uuid";

/** 托盘里的一项：本机文件（上传中 / upload / error）或项目文件引用（ref，现成的文件块）。 */
type Pending = { key: string; name: string; upload?: Upload; ref?: FileBlock; error?: string };

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** 输入框：文字 + 附件 + 语音。附件选中即上传，发送时只带上传 id。
 *  语音转成文字后填进输入框，让你看一眼再发（识别错了能改）。
 *  右下角只放一个主按钮：生成中是“停止”（Esc 同效），有内容时是“发送”，没内容时是“说话”。
 *  生成中照常能打字，说完再发。
 *  编辑态（editing 不为空）：顶部“编辑消息”条 + 原文字填进来；原附件随消息保留，这里的附件和草稿先收起，
 *  退出编辑（发出、取消、Esc）后原样回来。输入框为空时按 ↑ = 编辑最后一条（onEditLast）。
 *  打 @ → 顶部列出工作区文件（lib/mentions.ts）：↑↓ 选、Enter/Tab 补成 `@路径 `、Esc 收起；服务器发出时解析成引用。
 *  开头打 / → 列出斜杠命令（lib/slash.ts）：/init 原文发给服务器；本机命令（/new /compact /plan /copy /status）交给 onSlash
 *  （ChatScreen → slashActions.ts），不发消息，返回的一句提示显示在胶囊下方；点不接话的本机命令直接执行。
 *  @ 的第一行是“子助手”（v1.91，没有工作区也列）：补成 `@子助手 `，后端 app/agent_mentions.py 让模型交给子助手做。
 *  打 $ → 列出启用的技能（没有工作区也行），补成 `$id `；服务器 app/skill_mentions.py 把技能正文直接给模型。 */
export type EditDraft = { id: string; text: string; hasFiles: boolean };
type Props = {
  onSend: (t: string, files: OutgoingFile[]) => void; disabled: boolean; streaming?: boolean; onStop?: () => void;
  /** 生成中可以补一句给正在进行的这一轮（useChat.canSteer）：有字时停止钮换成“补充”钮。 */
  canSteer?: boolean;
  editing?: EditDraft | null; onCancelEdit?: () => void; onEditLast?: () => void;
  /** 主按钮左边的插槽（聊天页放模型钮，Composer 不认识它）。 */
  accessory?: ReactNode;
  /** 胶囊左边、胶囊外的圆钮位（一级页面聚焦时的“收起”）。 */
  leading?: ReactNode;
  placeholder?: string;
  /** 项目对话的项目 id：“添加附件”变成菜单，多一个“项目里的文件”（只带引用，不上传）。 */
  /** 这段对话的工作区（lib/workspace.ts）：“添加附件”多一个从它引用文件；不给 = 没有这个来源。 */
  workspace?: string;
  /** 本机斜杠命令的执行者（返回一句提示）；不给 = 不接本机命令（打了当普通文字发）。 */
  onSlash?: (c: SlashCall, files: OutgoingFile[]) => Promise<string | undefined> | void;
};
export default function Composer({ onSend, disabled, streaming = false, canSteer = false, onStop, editing = null, onCancelEdit, onEditLast, accessory, leading, placeholder = "给助手发消息", workspace, onSlash }: Props) {
  const [text, setText] = useState("");
  const stash = useRef<string | null>(null);   // 进入编辑前的草稿
  const editId = editing?.id ?? null;
  useEffect(() => {   // 进出编辑态：换文字、收起/放回草稿
    if (editId) {
      if (stash.current === null) stash.current = text;
      setText(editing!.text);
      ref.current?.focus();
    } else if (stash.current !== null) {
      setText(stash.current);
      stash.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editId]);
  const [files, setFiles] = useState<Pending[]>([]);
  const ref = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const mic = useRecorder();
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceErr, setVoiceErr] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [caret, setCaret] = useState(0);
  const [wsFiles, setWsFiles] = useState<{ ws: string; files: ProjectFile[] | null } | null>(null);
  const [skills, setSkills] = useState<Skill[] | null>(null);   // 第一次打 $ 时读；读过就不再读（技能页改了刷新页面即可）
  const [active, setActive] = useState(0);
  const [closedAt, setClosedAt] = useState<number | null>(null);   // Esc 收起的那个 @ 的位置（换个 @ 再弹）

  useEffect(() => {  // 自适应高度
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  const pick = (list: FileList | null) => {
    for (const f of Array.from(list ?? [])) {
      const key = uuid();
      setFiles((s) => [...s, { key, name: f.name }]);
      http.upload<Upload>("/api/uploads", f)
        .then((u) => setFiles((s) => s.map((x) => (x.key === key ? { ...x, upload: u } : x))))
        .catch((e) => setFiles((s) => s.map((x) => (x.key === key ? { ...x, error: String(e.message ?? e) } : x))));
    }
    if (picker.current) picker.current.value = "";
  };

  const uploading = files.some((f) => !f.upload && !f.ref && !f.error);
  const ready: FileBlock[] = files.flatMap((f) => (f.ref ? [f.ref] : f.upload ? [asFileBlock(f.upload)] : []));
  const takeRefs = (refs: FileBlock[]) => {
    setFiles((s) => [...s, ...refs.map((r) => ({ key: uuid(), name: r.name, ref: r }))]);
    setPicking(false);
    ref.current?.focus();
  };
  /** 整条是 `!命令`（且没带附件）：发出去不问助手，直接在这段对话的电脑上跑（后端 user_shell）。 */
  const shell = !editing && files.length === 0 && shellCommandOf(text) !== null;
  const sigils: Sigil[] = ["$", "@"];
  const found: MentionQuery | null = shellCommandOf(text) === null ? mentionAt(text, caret, sigils) : null;
  const slashQ = editing ? null : slashQueryAt(text, caret);
  const slash = slashQ !== null && closedAt !== 0 && rankSlash(slashQ, !!onSlash).length ? rankSlash(slashQ, !!onSlash) : null;
  /** 整条是一条斜杠命令（编辑时不认；不接话的本机命令带了附件不认）。 */
  const found0 = editing ? null : slashOf(text, !!onSlash);
  const command = found0 && found0.command.local && files.length > 0 && !found0.command.args ? null : found0;
  const local = !!command?.command.local;
  const runsNow = !!command && local && !slashBlocked(command, disabled);
  const [slashNote, setSlashNote] = useState<string | null>(null);
  useEffect(() => {   // 命令结果的一句提示：4 秒后自己收起
    if (!slashNote) return;
    const t = setTimeout(() => setSlashNote(null), 4000);
    return () => clearTimeout(t);
  }, [slashNote]);
  const runSlash = (c: SlashCall, withFiles: OutgoingFile[]) => {
    const r = onSlash?.(c, withFiles);
    if (r) r.then((note) => setSlashNote(note ?? null)).catch(() => setSlashNote("没做成，稍后再试"));
  };
  const mention = !slash && found && found.start !== closedAt ? found : null;
  const wantSkills = mention?.sigil === "$" && skills === null;
  useEffect(() => {   // 第一次打 $ 时才读技能
    if (!wantSkills) return;
    setSkills(null);
    http.get<Skill[]>("/api/catalog/skills").then(setSkills).catch(() => setSkills([]));
  }, [wantSkills]);
  useEffect(() => {   // 第一次打 @ 时才读文件列表；换工作区重读
    if (mention?.sigil !== "@" || !workspace || wsFiles?.ws === workspace) return;
    setWsFiles({ ws: workspace, files: null });
    http.get<ProjectFile[]>(`/api/projects/${workspace}/files`)
      .then((files) => setWsFiles({ ws: workspace, files }))
      .catch(() => setWsFiles({ ws: workspace, files: [] }));
  }, [mention, workspace, wsFiles?.ws]);
  const loaded = !workspace ? [] : wsFiles && wsFiles.ws === workspace ? wsFiles.files : null;
  const agentRow = mention?.sigil === "@" && agentMatches(mention.query);
  const items: MentionItem[] | null = slash
    ? slash.map((c) => ({ key: c.name, icon: slashIcon(c.icon), title: slashToken(c), sub: slashSubtitle(c, disabled) }))
    : !mention ? null
    : mention.sigil === "$"
      ? skills && rankSkills(skills, mention.query).map((s) => ({ key: s.id, icon: <IconSpark size={14} />, title: s.name, sub: s.description }))
      : loaded && [
          ...(agentRow ? [{ key: AGENT_MENTION, icon: <IconSplit size={14} />, title: AGENT_MENTION, sub: "交给子助手去做，只把结论交回来" }] : []),
          ...rankMentions(loaded, mention.query, agentRow ? MENTION_MAX - 1 : MENTION_MAX)
            .map((f) => ({ key: f.path, icon: <IconFile size={14} />, title: f.name, sub: projectFileLine(f) })),
        ];
  const choice = Math.min(active, Math.max((items?.length ?? 1) - 1, 0));
  const pickMention = (key: string) => {
    if (!mention && !slash) return;
    const picked = slash ? SLASH_COMMANDS.find((c) => c.name === key)! : null;
    if (picked?.local && !picked.args && !slashBlocked({ command: picked, args: "" }, disabled)) {
      setText(""); setCaret(0); setActive(0);   // Codex：不带参数的命令点了就执行
      runSlash({ command: picked, args: "" }, []);
      return;
    }
    const [next, at] = picked ? applySlash(picked) : applyMention(text, mention!, key);
    setText(next);
    setCaret(at);
    setActive(0);
    requestAnimationFrame(() => { ref.current?.focus(); ref.current?.setSelectionRange(at, at); });
  };
  const track = (el: HTMLTextAreaElement) => {
    setCaret(el.selectionStart === el.selectionEnd ? el.selectionStart : -1);
  };

  // 生成中有字或附件：发出去是补充给这一轮（lib/steer.ts），否则仍只能停止
  const steering = streaming && canSteer && steerable(text, { files: files.length, shell, editing: !!editing });
  const canSend = local ? runsNow && !uploading : (!disabled || steering) && (editing
    ? !!text.trim() || editing.hasFiles
    : !uploading && (!!text.trim() || ready.length > 0));

  const startVoice = async () => {
    setVoiceErr(null);
    try { await mic.start(); } catch { setVoiceErr("没有麦克风权限"); }
  };
  const finishVoice = async () => {
    const audio = await mic.stop();
    if (!audio) return;
    setVoiceBusy(true);
    try {
      const { text: heard } = await http.upload<{ text: string }>("/api/voice/transcribe", audio);
      setText((t) => (t ? `${t} ${heard}` : heard));
      ref.current?.focus();
    } catch (e) { setVoiceErr(e instanceof Error ? e.message : "识别失败"); }
    finally { setVoiceBusy(false); }
  };

  const submit = () => {
    if (!canSend) return;
    if (editing) { onSend(text.trim(), []); return; }   // 草稿由上面的 effect 在退出编辑时放回
    if (command && local) runSlash(command, ready);
    else onSend(text.trim(), ready);
    setText("");
    setCaret(0);
    setFiles([]);
  };

  return (
    <div className="composer-wrap">
      {leading}
      <div className={`composer glass ${editing ? "editing" : ""}`}>
        {slash && <MentionList items={items} active={choice} onPick={pickMention} onHover={setActive} label="命令" empty="" loading="" />}
        {mention && (mention.sigil === "$"
          ? <MentionList items={items} active={choice} onPick={pickMention} onHover={setActive} label="用技能"
              empty="没有对得上的技能 · 可以在“我的 › 技能”里新建" loading="正在读技能…" />
          : <MentionList items={items} active={choice} onPick={pickMention} onHover={setActive} label={workspace ? "引用文件或交给子助手" : "交给子助手"}
              empty={workspace ? "没有对得上的文件 · 发出去我也会按名字再找一次" : `打 @${AGENT_MENTION} 可以把这件事交给子助手`} loading="正在找文件…" />)}
        {!mention && !slash && !shell && command && (
          <div className="edit-bar shell-bar" key={`slash-${command.command.name}`}>
            {slashIcon(command.command.icon)}
            <span>{slashBarText(command, disabled)}</span>
          </div>
        )}
        {!mention && editing && (
          <div className="edit-bar">
            <IconEdit size={14} />
            <span>编辑消息 · 发送后重新回答</span>
            <button className="icon-btn sm" onClick={onCancelEdit} aria-label="取消编辑" title="取消编辑（Esc）"><IconClose size={14} /></button>
          </div>
        )}
        {!mention && shell && (
          <div className="edit-bar shell-bar">
            <IconTerminal size={14} />
            <span>直接在电脑上运行 · 不经过助手，结果它下次能看到</span>
          </div>
        )}
        {!editing && files.length > 0 && (
          <div className="attach-row">
            {files.map((f) => (
              <span key={f.key} className={`attach ${f.error ? "err" : ""} ${!f.upload && !f.ref && !f.error ? "loading" : ""}`} title={f.error ?? (f.ref ? `${workspaceFilesTitle(f.ref.project_id)} ${f.ref.id}` : f.name)}>
                <span className="attach-ext">{extOf(f.name)}{f.ref && <i className="attach-from" aria-label={workspaceFilesTitle(f.ref.project_id)}><IconFolder size={10} /></i>}</span>
                <span className="attach-text"><span className="attach-name">{f.name}</span><span className="attach-sub">{attachSub(f)}</span></span>
                <button onClick={() => setFiles((s) => s.filter((x) => x.key !== f.key))} aria-label="移除"><IconClose size={14} /></button>
              </span>
            ))}
          </div>
        )}
        {mic.state === "recording" ? (
          <div className="composer-row recording">
            <button className="icon-btn" onClick={mic.cancel} aria-label="取消录音"><IconClose /></button>
            <div className="rec-meter"><i className="rec-dot" />正在听… {clock(mic.seconds)}</div>
            <button className="send-btn" onClick={finishVoice} aria-label="完成"><IconCheck /></button>
          </div>
        ) : (
          <div className="composer-row">
            {workspace && !editing
              ? <Menu label="添加附件" trigger={<IconClip />} items={[
                  { label: "从电脑选文件", icon: <IconFile size={16} />, onSelect: () => picker.current?.click() },
                  { label: workspaceFilesTitle(workspace), icon: <IconFolder size={16} />, onSelect: () => setPicking(true) },
                ]} />
              : <button className="icon-btn" onClick={() => picker.current?.click()} disabled={!!editing} aria-label="添加附件"><IconClip /></button>}
            <input ref={picker} type="file" multiple hidden onChange={(e) => pick(e.target.files)} />
            <textarea ref={ref} rows={1} value={text} placeholder={voiceBusy ? "正在识别…" : streaming && canSteer && !editing ? STEER_HINT : placeholder}
              onChange={(e) => { setText(e.target.value); track(e.target); setActive(0); if (closedAt !== null && !"@$/".includes(e.target.value[closedAt] ?? "x")) setClosedAt(null); }}
              onSelect={(e) => track(e.currentTarget)}
              onPaste={(e) => !editing && e.clipboardData.files.length && pick(e.clipboardData.files)}
              onKeyDown={(e) => {
                if ((mention || slash) && !e.nativeEvent.isComposing) {
                  const n = items?.length ?? 0;
                  if (e.key === "ArrowDown" && n) { e.preventDefault(); setActive((choice + 1) % n); return; }
                  if (e.key === "ArrowUp" && n) { e.preventDefault(); setActive((choice - 1 + n) % n); return; }
                  if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && n) { e.preventDefault(); pickMention(items![choice].key); return; }
                  if (e.key === "Escape") { e.preventDefault(); setClosedAt(slash ? 0 : mention!.start); return; }
                }
                if (e.key === "Escape" && streaming) { e.preventDefault(); onStop?.(); }
                else if (e.key === "Escape" && editing) { e.preventDefault(); onCancelEdit?.(); }
                if (e.key === "ArrowUp" && !text && !editing && onEditLast) { e.preventDefault(); onEditLast(); }
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
              }} />
            {accessory}
            {streaming && !steering && !runsNow
              ? <button key="stop" className="send-btn stop" onClick={onStop} disabled={!onStop} aria-label="停止生成" title="停止生成（Esc）"><IconStop /></button>
              : canSend || !mic.supported
              ? <button key={steering ? "steer" : shell ? "run" : local ? "slash" : "send"} className="send-btn" onClick={submit} disabled={!canSend}
                  aria-label={editing ? "保存并重新回答" : shell ? "在电脑上运行" : steering ? "补充给正在进行的回答" : local ? `执行 ${slashToken(command!.command)}` : "发送"}
                  title={shell ? "在电脑上运行（Enter）" : local ? "执行（Enter）" : undefined}>
                  {shell ? <IconTerminal /> : local ? <IconCheck /> : <IconSend />}</button>
              : <button className="send-btn ghost" onClick={startVoice} disabled={disabled || voiceBusy} aria-label="说话"><IconMic /></button>}
          </div>
        )}
        {voiceErr && <div className="composer-hint err" onClick={() => setVoiceErr(null)}>{voiceErr}</div>}
        {slashNote && <div className="composer-hint slash-note" role="status" onClick={() => setSlashNote(null)}>{slashNote}</div>}
      </div>
      {picking && workspace && (
        <ProjectFilePicker projectId={workspace} onClose={() => setPicking(false)} onPick={takeRefs}
          taken={new Set(files.flatMap((f) => (f.ref ? [f.ref.id] : [])))} room={MAX_MESSAGE_FILES - files.length} />
      )}
    </div>
  );
}

/** 斜杠命令的图标（lib/slash.ts 只存名字，图标组件在这里对上）。 */
function slashIcon(icon: SlashIcon) {
  const C = { doc: IconDoc, plus: IconPlus, brain: IconBrain, map: IconMap, copy: IconCopy, gauge: IconGauge, swap: IconSwap, edit: IconEdit }[icon];
  return <C size={14} />;
}
