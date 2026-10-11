/** 朗读：用系统自带的语音合成（免费、无需联网到模型）。同一时间只读一段。 */
const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
let current: SpeechSynthesisUtterance | null = null;

export const speechSupported = !!synth;

export function speak(text: string, onEnd: () => void): void {
  if (!synth) return;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[#*`>|_]/g, "")); // 去掉 Markdown 符号
  u.lang = /[\u4e00-\u9fa5]/.test(text) ? "zh-CN" : "en-US";
  u.rate = 1.05;
  u.onend = u.onerror = () => { if (current === u) current = null; onEnd(); };
  current = u;
  synth.speak(u);
}

export function stopSpeaking(): void {
  current = null;
  synth?.cancel();
}
