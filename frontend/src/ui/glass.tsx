import type { ReactNode } from "react";
import { IconPlus, IconUser } from "./icons";

/** 设计 v2 零件的 React 外壳（样式全在 glass.css，和 App ui/glass.dart 同名同义）。 */
export function ValueTile({ label, value, note }: { label: string; value: string; note?: string | null }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

/** 整行宽的玻璃胶囊入口。 */
export function WidePill({ label, icon = <IconPlus size={18} />, onClick }: { label: string; icon?: ReactNode; onClick: () => void }) {
  return <button className="wide-pill" onClick={onClick}>{icon}{label}</button>;
}

/** 圆形头像：底色 = 偏好里的头像色（--avatar），上面的图标颜色自动选白/深。 */
export function Avatar({ large, onClick, label }: { large?: boolean; onClick?: () => void; label?: string }) {
  const icon = <IconUser size={large ? 34 : 20} />;
  return onClick
    ? <button className={`avatar ${large ? "lg" : ""}`} onClick={onClick} aria-label={label} title={label}>{icon}</button>
    : <span className={`avatar ${large ? "lg" : ""}`} aria-hidden>{icon}</span>;
}
