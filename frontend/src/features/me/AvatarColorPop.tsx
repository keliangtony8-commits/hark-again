import { type RefObject, useEffect, useRef } from "react";
import { AVATAR_PRESETS, colorHue, hueColor, setAvatarColor, useLook } from "../../lib/look";
import { IconCheck } from "../../ui/icons";

const RING = Array.from({ length: 13 }, (_, i) => hueColor((i * 30) % 360)).join(", ");

/** 头像色弹层：4 个预设 + 色轮（只选色相，饱和度/明度固定）。点外面 / Esc 关。和 App features/me/avatar_color_sheet.dart 同义。
 *  只改头像色，不动强调色（避免对比度问题）；只存本机。 */
/** boundary：点在它里面不算“点外面”（放头像 + 弹层的那个容器，免得点头像关了又开）。 */
export default function AvatarColorPop({ onClose, boundary }: { onClose: () => void; boundary: RefObject<HTMLElement> }) {
  const { avatar } = useLook();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !(boundary.current ?? ref.current)?.contains(e.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [onClose, boundary]);

  const hue = avatar ? colorHue(avatar) : null;
  const preset = avatar === null || AVATAR_PRESETS.includes(avatar);
  // 色轮：0° 在正上方，顺时针；点哪儿取哪儿的色相（conic-gradient 的起点同样在正上方）
  const pickHue = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.type === "pointermove" && e.buttons !== 1) return;
    const r = e.currentTarget.getBoundingClientRect();
    const deg = (Math.atan2(e.clientX - (r.left + r.width / 2), -(e.clientY - (r.top + r.height / 2))) * 180) / Math.PI;
    setAvatarColor(hueColor(Math.round((deg + 360) % 360)));
  };

  return (
    <div className="avatar-pop glass raised" ref={ref} role="dialog" aria-label="头像颜色">
      <div className="avatar-pop-title">头像颜色</div>
      <div className="avatar-swatches" role="radiogroup" aria-label="预设颜色">
        <button role="radio" aria-checked={avatar === null} aria-label="默认（中性）" className={`swatch neutral ${avatar === null ? "on" : ""}`}
          onClick={() => setAvatarColor(null)}>{avatar === null && <IconCheck size={16} />}</button>
        {AVATAR_PRESETS.map((c) => (
          <button key={c} role="radio" aria-checked={c === avatar} aria-label={c} className={`swatch ${c === avatar ? "on" : ""}`}
            style={{ background: c }} onClick={() => setAvatarColor(c)}>{c === avatar && <IconCheck size={16} />}</button>
        ))}
      </div>
      <div className="hue-wheel" style={{ background: `conic-gradient(${RING})` }} onPointerDown={pickHue} onPointerMove={pickHue}
        role="slider" aria-label="色相" aria-valuemin={0} aria-valuemax={360} aria-valuenow={Math.round(hue ?? 0)} tabIndex={0}
        onKeyDown={(e) => {
          const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 10 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -10 : 0;
          if (step) { e.preventDefault(); setAvatarColor(hueColor(((hue ?? 0) + step + 360) % 360)); }
        }}>
        <span className="hue-hole" style={{ background: avatar ?? "var(--avatar)" }} />
        {hue !== null && !preset && <span className="hue-knob" style={{ transform: `rotate(${hue}deg)` }}><i style={{ background: avatar ?? undefined }} /></span>}
      </div>
    </div>
  );
}
