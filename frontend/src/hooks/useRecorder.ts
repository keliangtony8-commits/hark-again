import { useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "recording";

/** 麦克风录音：start() 开始，stop() 拿到音频，cancel() 丢弃。只管录音，不管上传。 */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number>();

  const release = () => {
    window.clearInterval(timer.current);
    rec.current?.stream.getTracks().forEach((t) => t.stop());
    rec.current = null;
    setState("idle");
  };
  useEffect(() => release, []);

  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const r = new MediaRecorder(stream);
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.start();
    rec.current = r;
    setSeconds(0);
    setState("recording");
    timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
  };

  const stop = () => new Promise<File | null>((resolve) => {
    const r = rec.current;
    if (!r) return resolve(null);
    r.onstop = () => {
      const type = r.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      resolve(new File(chunks.current, `voice.${ext}`, { type }));
      release();
    };
    r.stop();
  });

  const cancel = () => { if (rec.current) { rec.current.onstop = null; rec.current.stop(); } release(); };

  return { state, seconds, start, stop, cancel, supported: typeof MediaRecorder !== "undefined" };
}
