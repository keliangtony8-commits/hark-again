import { type ReactNode, useEffect, useRef, useState } from "react";
import { workspaceFilesTitle } from "../../lib/workspace";
import { http } from "../../lib/api";
import { asFileBlock, attachSub, extOf, MAX_MESSAGE_FILES } from "../../lib/files";
import type { FileBlock, OutgoingFile, Upload } from "../../lib/types";
import ProjectFilePicker from "../projects/ProjectFilePicker";
import { useRecorder } from "../../hooks/useRecorder";
import { IconCheck, IconClip, IconClose, IconEdit, IconFile, IconFolder, IconMic, IconSend, IconStop, IconTerminal } from "../../ui/icons";
import { shellCommandOf } from "../../lib/shell";
import { Menu } from "../../ui/kit";
import { applyMention, mentionAt, rankMentions, type MentionQuery } from "../../lib/mentions";
import type { ProjectFile } from "../../lib/types";
import MentionList from "./MentionList";
import "./chat.css";

/** 托盘里的一项：本机文件（上传中 / upload / error）或项目文件引用（ref，现成的文件块）。 */
type Pending = { key: string; name: string; upload?: Upload; ref?: FileBlock; error?: string };

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** 输入框：文字 + 附件 + 语音。附件选中即上传，发送时只带上传 id。
 *  语音转成文字后填进输入框，让你看一眼再发（识别错了能改）。
 *  右下角只放一个主按钮：生成中是“停止”（Esc 同效），有内容时是“发送”，没内容时是“说话”。
 *  生成中照常能打字，说完再发。
 *  编辑态（editing 不为空）：顶部“编辑消息”条 + 原文字填进来；原附件随消息保留，这里的附件和草稿先收起，
 *  退出编辑（发出、取消、Esc）后原样回来。输入框为空时按 ↑ = 编辑最后一条（onEditLast）。
 *  打 @ → 顶部列出工作区文件（lib/mentions.ts）：↑↓ 选、Enter/Tab 补成 `@路径 `、Esc 收起；服务器发出时解析成引用。 */
export type EditDraft = { id: string; text: string; hasFiles: boolean };
type Props = {
  onSend: (t: string, files: OutgoingFile[]) => void; disabled: boolean; streaming?: boolean; onStop?: () => void;
  editing?: EditDraft | null; onCancelEdit?: () => void; onEditLast?: () => void;
  /** 主按钮左边的插槽（聊天页放模型钮，Composer 不认识它）。 */
  accessory?: ReactNode;
  /** 胶囊左边、胶囊外的圆钮位（一级页面聚焦时的“收起”）。 */
  leading?: ReactNode;
  placeholder?: string;
  /** 项目对话的项目 id：“添加附件”变成菜单，多一个“项目里的文件”（只带引用，不上传）。 */
  /** 这段对话的工作区（lib/workspace.ts）：“添加附件”多一个从它引用文件；不给 = 没有这个来源。 */
  workspace?: string;
};
export default function Composer({ onSend, disabled, streaming = false, onStop, editing = null, onCancelEdit, onEditLast, accessory, leading, placeholder = "给助手发消息", workspace }: Props) {
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
      const key = crypto.randomUUID();
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
    setFiles((s) => [...s, ...refs.map((r) => ({ key: crypto.randomUUID(), name: r.name, ref: r }))]);
    setPicking(false);
    ref.current?.focus();
  };
  /** 整条是 `!命令`（且没带附件）：发出去不问助手，直接在这段对话的电脑上跑（后端 user_shell）。 */
  const shell = !editing && files.length === 0 && shellCommandOf(text) !== null;
  const found: MentionQuery | null = workspace && shellCommandOf(text) === null ? mentionAt(text, caret) : null;
  const mention = found && found.start !== closedAt ? found : null;
  useEffect(() => {   // 第一次打 @ 时才读文件列表；换工作区重读
    if (!mention || !workspace || wsFiles?.ws === workspace) return;
    setWsFiles({ ws: workspace, files: null });
    http.get<ProjectFile[]>(`/api/projects/${workspace}/files`)
      .then((files) => setWsFiles({ ws: workspace, files }))
      .catch(() => setWsFiles({ ws: workspace, files: [] }));
  }, [mention, workspace, wsFiles?.ws]);
  const loaded = wsFiles && wsFiles.ws === workspace ? wsFiles.files : null;
  const mentionFiles = mention && loaded ? rankMentions(loaded, mention.query) : null;
  const choice = Math.min(active, Math.max((mentionFiles?.length ?? 1) - 1, 0));
  const pickMention = (f: ProjectFile) => {
    if (!mention) return;
    const [next, at] = applyMention(text, mention, f.path);
    setText(next);
    setCaret(at);
    setActive(0);
    requestAnimationFrame(() => { ref.current?.focus(); ref.current?.setSelectionRange(at, at); });
  };
  const track = (el: HTMLTextAreaElement) => {
    setCaret(el.selectionStart === el.selectionEnd ? el.selectionStart : -1);
  };

  const canSend = !disabled && (editing
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
    onSend(text.trim(), ready);
    setText("");
    setCaret(0);
    setFiles([]);
  };

  return (
    <div className="composer-wrap">
      {leading}
      <div className={`composer glass ${editing ? "editing" : ""}`}>
        {mention && <MentionList files={mentionFiles} active={choice} onPick={pickMention} onHover={setActive} />}
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
            <textarea ref={ref} rows={1} value={text} placeholder={voiceBusy ? "正在识别…" : placeholder}
              onChange={(e) => { setText(e.target.value); track(e.target); setActive(0); if (closedAt !== null && e.target.value[closedAt] !== "@") setClosedAt(null); }}
              onSelect={(e) => track(e.currentTarget)}
              onPaste={(e) => !editing && e.clipboardData.files.length && pick(e.clipboardData.files)}
              onKeyDown={(e) => {
                if (mention && !e.nativeEvent.isComposing) {
                  const n = mentionFiles?.length ?? 0;
                  if (e.key === "ArrowDown" && n) { e.preventDefault(); setActive((choice + 1) % n); return; }
                  if (e.key === "ArrowUp" && n) { e.preventDefault(); setActive((choice - 1 + n) % n); return; }
                  if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && n) { e.preventDefault(); pickMention(mentionFiles![choice]); return; }
                  if (e.key === "Escape") { e.preventDefault(); setClosedAt(mention.start); return; }
                }
                if (e.key === "Escape" && streaming) { e.preventDefault(); onStop?.(); }
                else if (e.key === "Escape" && editing) { e.preventDefault(); onCancelEdit?.(); }
                if (e.key === "ArrowUp" && !text && !editing && onEditLast) { e.preventDefault(); onEditLast(); }
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
              }} />
            {accessory}
            {streaming
              ? <button key="stop" className="send-btn stop" onClick={onStop} disabled={!onStop} aria-label="停止生成" title="停止生成（Esc）"><IconStop /></button>
              : canSend || !mic.supported
              ? <button key={shell ? "run" : "send"} className="send-btn" onClick={submit} disabled={!canSend}
                  aria-label={editing ? "保存并重新回答" : shell ? "在电脑上运行" : "发送"} title={shell ? "在电脑上运行（Enter）" : undefined}>
                  {shell ? <IconTerminal /> : <IconSend />}</button>
              : <button className="send-btn ghost" onClick={startVoice} disabled={disabled || voiceBusy} aria-label="说话"><IconMic /></button>}
          </div>
        )}
        {voiceErr && <div className="composer-hint err" onClick={() => setVoiceErr(null)}>{voiceErr}</div>}
      </div>
      {picking && workspace && (
        <ProjectFilePicker projectId={workspace} onClose={() => setPicking(false)} onPick={takeRefs}
          taken={new Set(files.flatMap((f) => (f.ref ? [f.ref.id] : [])))} room={MAX_MESSAGE_FILES - files.length} />
      )}
    </div>
  );
}
