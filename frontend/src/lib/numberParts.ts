/** 一个展示值里“唯一的那个数字”（面板关键数字滚动用），= App ui/format.dart NumberParts，规则一字不差：
 *  只认恰好一个数字；'17:42'、'2026-10-11'、'3/5'、没数字的返回 null（原样显示不滚）；正负号留在前缀里。 */
export type NumberParts = { prefix: string; value: number; decimals: number; grouped: boolean; suffix: string };

const MAX_DIGITS = 15;

export function parseNumber(s: string): NumberParts | null {
  const all = [...s.matchAll(/\d[\d,]*(?:\.\d+)?/g)];
  if (all.length !== 1) return null;
  const m = all[0];
  const raw = m[0];
  const grouped = raw.includes(",");
  if (grouped && !/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(raw)) return null;
  const plain = raw.replace(/,/g, "");
  if (plain.replace(".", "").length > MAX_DIGITS) return null;
  const dot = plain.indexOf(".");
  const start = m.index ?? 0;
  return { prefix: s.slice(0, start), value: Number(plain), decimals: dot < 0 ? 0 : plain.length - dot - 1, grouped, suffix: s.slice(start + raw.length) };
}

export function formatNumber(p: NumberParts, v: number): string {
  let n = Math.abs(v).toFixed(p.decimals);
  if (p.grouped) {
    const [whole, frac] = n.split(".");
    n = whole.replace(/\B(?=(\d{3})+$)/g, ",") + (frac !== undefined ? `.${frac}` : "");
  }
  return `${p.prefix}${n}${p.suffix}`;
}

/** 前后缀、小数位一样才能“接着滚”，否则直接换字。 */
export const sameShape = (a: NumberParts, b: NumberParts) => a.prefix === b.prefix && a.suffix === b.suffix && a.decimals === b.decimals;
