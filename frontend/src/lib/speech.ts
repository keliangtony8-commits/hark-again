/**
 * 朗读：网页唯一的播放入口。同一时间只读一段：读别的先停当前的；再点同一条 = 停。
 * 状态（哪条消息、准备中还是在读）放在模块里的小 store，按钮用 useSpeechPhase(id) 订阅，所以读另一条时旧按钮自动复位。
 * - 服务器开了云端朗读（GET /api/voice/config → tts=server）→ POST /api/voice/speak 拿 mp3 用 <audio> 播；
 * - 否则、老服务器、或这次云端朗读失败 → 浏览器自带的 speechSynthesis（免费、离线）。
 */
import { useSyncExternalStore } from "react";
import { http, server } from "./api";

const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

/** 有没有任何一条朗读路径（云端要等问过服务器才知道；有 <audio> 就先给按钮，没云端时退回系统语音）。 */
export const speechSupported = !!synth || typeof Audio !== "undefined";

let round = 0; // 每次开始/停止 +1，旧轮次的回调一律忽略
let audio: HTMLAudioElement | null = null;
let audioUrl: string | null = null;
let mode: { server: string; tts: "server" | "device" } | null = null;

async function voiceMode(): Promise<"server" | "device"> {
  const srv = server.get();
  if (mode && mode.server === srv) return mode.tts;
  try {
    const cfg = await http.get<{ tts?: string }>("/api/voice/config");
    mode = { server: srv, tts: cfg.tts === "server" ? "server" : "device" };
  } catch (e) {
    if (e instanceof TypeError) return "device"; // 连不上：不记住，下次再问
    mode = { server: srv, tts: "device" }; // 老服务器没有这个接口
  }
  return mode.tts;
}

/** 正文里值得读的部分：去 Markdown 记号，链接读文字，不读网址和代码。 */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[#*`>|_~]/g, "")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

function releaseAudio() {
  if (audio) { audio.onended = audio.onerror = null; audio.pause(); audio = null; }
  if (audioUrl) { URL.revokeObjectURL(audioUrl); audioUrl = null; }
}

function speakDevice(text: string, my: number, onEnd: () => void) {
  if (!synth) { onEnd(); return; }
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = /[\u4e00-\u9fa5]/.test(text) ? "zh-CN" : "en-US";
  u.rate = 1.05;
  u.onend = u.onerror = () => { if (my === round) onEnd(); };
  synth.speak(u);
}

export type SpeechPhase = "idle" | "loading" | "playing";
let current: { id: string; phase: SpeechPhase } | null = null;
const listeners = new Set<() => void>();
function setCurrent(next: typeof current) { current = next; listeners.forEach((l) => l()); }
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** 某条消息的朗读状态（只有这条变了才重渲染）。 */
export function useSpeechPhase(id: string): SpeechPhase {
  return useSyncExternalStore(subscribe, () => (current?.id === id ? current.phase : "idle"));
}

/** 点“朗读”：同一条在读 → 停；否则停掉别的、读这条。 */
export async function toggleSpeech(id: string, text: string): Promise<void> {
  if (current?.id === id) { stopSpeaking(); return; }
  stopSpeaking();
  const my = ++round;
  const spoken = speakable(text);
  if (!spoken) return;
  const end = () => { if (my === round) setCurrent(null); };
  const playing = () => { if (my === round) setCurrent({ id, phase: "playing" }); };
  setCurrent({ id, phase: "loading" });
  if ((await voiceMode()) === "server") {
    try {
      const blob = await http.postBlob("/api/voice/speak", { text: spoken });
      if (my !== round) return;
      audioUrl = URL.createObjectURL(blob);
      audio = new Audio(audioUrl);
      audio.onended = audio.onerror = () => { if (my === round) { releaseAudio(); end(); } };
      await audio.play();
      playing();
      return;
    } catch (e) {
      if (e instanceof Error && e.message === "未登录") { end(); return; }
      /* 云端这次不行（额度、网络、浏览器拒绝自动播放）→ 退回浏览器语音 */
    }
    if (my !== round) return;
    releaseAudio();
  }
  if (!synth) { end(); return; }
  speakDevice(spoken, my, end);
  playing();
}

/** 这条消息离开屏幕（换对话、离开聊天、被重新生成替换）时：它在读就停。 */
export function stopIfSpeaking(id: string): void {
  if (current?.id === id) stopSpeaking();
}

export function stopSpeaking(): void {
  round++;
  releaseAudio();
  synth?.cancel();
  if (current) setCurrent(null);
}
