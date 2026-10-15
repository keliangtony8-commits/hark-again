import type { ReactNode } from "react";
import CountUp from "./CountUp";
import { IconPlus } from "./icons";
import { fileUrl } from "../lib/api";
import { profileInitial, useProfile } from "../lib/profile";

/** 设计 v2 零件的 React 外壳（样式全在 glass.css，和 App ui/glass.dart 同名同义）。 */
export function ValueTile({ label, value, note }: { label: string; value: string; note?: string | null }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value"><CountUp value={value} /></div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

/** 整行宽的玻璃胶囊入口。 */
export function WidePill({ label, icon = <IconPlus size={18} />, onClick }: { label: string; icon?: ReactNode; onClick: () => void }) {
  return <button className="wide-pill" onClick={onClick}>{icon}{label}</button>;
}

/** 圆形头像：底色 = 偏好里的头像色（--avatar），上面是首字母（字色自动选白/深）；v2.92 §P 上传过头像就盖一张图（= App Avatar）。资料来自 lib/profile.ts（当前登录用户）。 */
export function Avatar({ large, onClick, label }: { large?: boolean; onClick?: () => void; label?: string }) {
  const p = useProfile();
  const body = <>
    <span className="avatar-initial">{profileInitial(p)}</span>
    {p?.avatar && <img key={p.avatar} className="avatar-img" src={fileUrl(p.avatar)} alt="" draggable={false}
      onLoad={(e) => e.currentTarget.classList.add("on")} onError={(e) => e.currentTarget.remove()} />}
  </>;
  return onClick
    ? <button className={`avatar ${large ? "lg" : ""}`} onClick={onClick} aria-label={label} title={label}>{body}</button>
    : <span className={`avatar ${large ? "lg" : ""}`} aria-hidden>{body}</span>;
}
