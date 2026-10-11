import { useEffect, useRef, useState } from "react";
import { fileUrl, http } from "../lib/api";
import type { BrowserBlock as T } from "../lib/types";
import { IconGlobe, IconHand, IconSend } from "../ui/icons";

const INTERVAL = 1200;

/** 云浏览器实时画面：只在卡片可见、页面在前台时刷新截图（省流量）。
 *  点“接管”后，点画面 = 点网页，下方输入框 = 键盘（用来输密码、过验证码）。 */
export default function BrowserBlock(_: { block: T }) {
  const box = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [tick, setTick] = useState(0);
  const [broken, setBroken] = useState(false);
  const [control, setControl] = useState(false);
  const [keys, setKeys] = useState("");

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting));
    if (box.current) io.observe(box.current);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    const id = setInterval(() => { if (!document.hidden) setTick((t) => t + 1); }, INTERVAL);
    return () => clearInterval(id);
  }, [visible]);

  const click = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!control) return;
    const r = e.currentTarget.getBoundingClientRect();
    http.post("/api/browser/mouse", { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height });
  };
  const sendKeys = async () => {
    await http.post("/api/browser/keyboard", keys ? { text: keys, key: "Enter" } : { key: "Enter" });
    setKeys("");
  };

  return (
    <div ref={box} className={`card blk-browser ${control ? "control" : ""}`}>
      <div className="card-head">
        <span className="blk-browser-title"><IconGlobe size={16} />云浏览器{visible && !broken && <i className="live-dot" />}</span>
        <button className={`btn btn-sm ${control ? "btn-primary" : "btn-ghost"}`} onClick={() => setControl(!control)}>
          <IconHand />{control ? "交还给我" : "接管"}</button>
      </div>
      {broken ? (
        <button className="blk-browser-empty" onClick={() => setBroken(false)}>浏览器没有打开或已休眠，点此重试</button>
      ) : (
        <img className="blk-browser-screen" alt="浏览器画面" onClick={click}
          src={`${fileUrl("/api/browser/screen")}&t=${tick}`} onError={() => setBroken(true)} onLoad={() => setBroken(false)} />
      )}
      {control && (
        <div className="blk-browser-keys">
          <input value={keys} onChange={(e) => setKeys(e.target.value)} placeholder="先点画面里的输入框，再在这里打字"
            type="text" autoComplete="off" onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && sendKeys()} />
          <button className="send-btn" onClick={sendKeys} aria-label="输入"><IconSend /></button>
        </div>
      )}
    </div>
  );
}
