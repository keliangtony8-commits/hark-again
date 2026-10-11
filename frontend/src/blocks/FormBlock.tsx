import { useRef, useState } from "react";
import type { FormBlock as F, FormInput } from "../lib/types";
import { useBlockActions } from "./actions";
import { IconCheck, IconEdit, IconEye, IconEyeOff, IconLock, IconSms } from "../ui/icons";
import { Toggle } from "../ui/kit";

const STATE_TEXT: Record<F["state"], string> = { pending: "等你填写", submitted: "已填写", cancelled: "已取消", expired: "已过期" };
const AUTOCOMPLETE = { password: "current-password", code: "one-time-code", email: "email" } as const;

/** 表单卡：浏览器任务里向你要登录信息或验证码（对标 Hark “在它自己的表单上问你”）。
 *  等填写：输入框 + 取消 / 提交（填满才能点）；登录卡是真正的 <form autocomplete>，浏览器密码管理器能直接填。
 *  发出后清空并收起，只剩状态；值从不进卡片。断线（replyForm 返回 false）保留输入。 */
export default function FormBlock({ block }: { block: F }) {
  const { replyForm } = useBlockActions();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(block.fields.map((f) => [f.name, f.value ?? ""])));
  const [shown, setShown] = useState<Set<string>>(new Set());
  const [remember, setRemember] = useState(false);
  const [sent, setSent] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const open = block.state === "pending" && !!replyForm && !sent;
  const complete = block.fields.every((f) => (values[f.name] ?? "").trim());
  const Icon = block.state === "submitted" ? IconCheck : block.purpose === "login" ? IconLock : block.purpose === "code" ? IconSms : IconEdit;

  const reply = (submit: boolean) => {
    if (!replyForm || sent || (submit && !complete)) return;
    if (!replyForm(block.id, submit ? values : null, submit && remember)) return;
    setSent(true);
    setValues({});
  };

  return (
    <section className={`card blk-form ${block.state}`} aria-label={`${block.title}${block.site ? "，" + block.site : ""}，${STATE_TEXT[block.state]}`}>
      <header className="blk-form-head">
        <span key={block.state} className="icon-pop"><Icon size={18} /></span>
        <span className="blk-form-title">{block.title}{block.site && <small>{block.site}</small>}</span>
        <span key={"s" + block.state} className="blk-form-state icon-pop">{STATE_TEXT[block.state]}</span>
      </header>
      {open && (
        <form className="blk-form-body fade-in" autoComplete="on" onSubmit={(e) => { e.preventDefault(); reply(true); }}>
          {block.fields.map((f, i) => (
            <Field key={f.name} field={f} login={block.purpose === "login"} value={values[f.name] ?? ""}
              inputRef={i === 0 ? first : undefined} autoFocus={i === 0 && block.fields.every((x) => !x.value)}
              shown={shown.has(f.name)} onShow={() => setShown((s) => { const n = new Set(s); n.has(f.name) ? n.delete(f.name) : n.add(f.name); return n; })}
              onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))} />
          ))}
          {block.remember && (
            <label className="blk-form-remember">
              <span>记住到保险箱，下次自动登录</span>
              <Toggle on={remember} onChange={setRemember} label="记住到保险箱" />
            </label>
          )}
          <p className="blk-form-note"><IconEyeOff size={14} />只交给浏览器填写，助手看不到</p>
          <div className="blk-form-actions">
            <button type="button" className="btn btn-ghost" onClick={() => reply(false)}>取消</button>
            <button type="submit" className="btn btn-primary" disabled={!complete}>{block.action || "提交"}</button>
          </div>
        </form>
      )}
    </section>
  );
}

function Field({ field, login, value, onChange, shown, onShow, autoFocus, inputRef }: {
  field: FormInput; login: boolean; value: string; onChange: (v: string) => void; shown: boolean; onShow: () => void;
  autoFocus: boolean; inputRef?: React.Ref<HTMLInputElement>;
}) {
  const kind = field.kind ?? "text";
  const secret = kind === "password";
  return (
    <label className="form-field blk-form-field">
      <span>{field.label}</span>
      <div className="blk-form-input">
        <input ref={inputRef} name={field.name} value={value} autoFocus={autoFocus} spellCheck={false} autoCapitalize="off"
          type={secret && !shown ? "password" : kind === "email" ? "email" : "text"}
          inputMode={kind === "code" ? "numeric" : undefined}
          autoComplete={kind === "text" ? (login ? "username" : "off") : AUTOCOMPLETE[kind]}
          onChange={(e) => onChange(e.target.value)} />
        {secret && (
          <button type="button" className="blk-form-eye" aria-label={shown ? "隐藏密码" : "显示密码"} onClick={onShow}>
            {shown ? <IconEyeOff size={18} /> : <IconEye size={18} />}
          </button>
        )}
      </div>
    </label>
  );
}
