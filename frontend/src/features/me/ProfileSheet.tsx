import { useRef, useState } from "react";
import { clearAvatar, renameProfile, uploadAvatar, useProfile } from "../../lib/profile";
import { Avatar } from "../../ui/glass";
import { Sheet } from "../../ui/kit";

/** v2.92 §P 改称呼 / 助手名 / 头像（= App features/me/profile_sheet.dart）：“我的”页点名字或头像打开。
 *  头像选了立刻上传（浏览器先缩到 512px 的 JPEG），名字点保存才送，只送改了的字段。 */
export default function ProfileSheet({ onClose }: { onClose: () => void }) {
  const p = useProfile();
  const start = useRef({ name: p?.display_name ?? "", assistant: p?.assistant_name ?? "" });
  const [name, setName] = useState(start.current.name);
  const [assistant, setAssistant] = useState(start.current.assistant);
  const [busy, setBusy] = useState<"save" | "photo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const fallback = p?.assistant_default ?? "Toyuis";

  const save = async () => {
    const fields: { display_name?: string; assistant_name?: string } = {};
    if (name.trim() !== start.current.name) fields.display_name = name.trim();
    if (assistant.trim() !== start.current.assistant) fields.assistant_name = assistant.trim();
    if (!Object.keys(fields).length) return onClose();
    setBusy("save"); setError(null);
    try { await renameProfile(fields); onClose(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  const photo = async (f: File | undefined) => {
    if (!f) return;
    setBusy("photo"); setError(null);
    try { await uploadAvatar(await shrink(f)); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  const removePhoto = async () => {
    setBusy("photo"); setError(null);
    try { await clearAvatar(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <Sheet title="个人资料" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={busy !== null} onClick={() => void save()}>保存</button>
    </>}>
      <div className="profile-photo">
        <Avatar large onClick={() => picker.current?.click()} label="更换头像" />
        <div className="profile-photo-actions">
          <button className="pill" disabled={busy !== null} onClick={() => picker.current?.click()}>{busy === "photo" ? "上传中…" : "更换头像"}</button>
          {p?.avatar && <button className="pill" disabled={busy !== null} onClick={() => void removePhoto()}>移除</button>}
        </div>
        <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" hidden
          onChange={(e) => { void photo(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      <label className="form-field"><span>我该如何称呼你</span>
        <input value={name} maxLength={20} placeholder={p?.username} onChange={(e) => setName(e.target.value)} autoFocus /></label>
      <label className="form-field"><span>助手的名字</span>
        <input value={assistant} maxLength={20} placeholder={fallback} onChange={(e) => setAssistant(e.target.value)} />
        <small>留空就叫 {fallback}</small></label>
      {error && <small className="form-error" role="alert">{error}</small>}
    </Sheet>
  );
}

/** 缩到最长边 512px 的 JPEG（服务器上限 2 MB，原图常常几 MB）；读不了的图原样上传，让服务器给出准确的错误。 */
async function shrink(f: File): Promise<File> {
  try {
    const img = await createImageBitmap(f);
    const k = Math.min(1, 512 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext("2d")?.drawImage(img, 0, 0, c.width, c.height);
    const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.85));
    return blob ? new File([blob], "avatar.jpg", { type: "image/jpeg" }) : f;
  } catch {
    return f;
  }
}
