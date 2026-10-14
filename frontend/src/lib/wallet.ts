/** 钱包（v2.74，后端 app/wallet.py；App models/wallet.dart 同一套规则）：卡组织、分组、Luhn（银联放宽）、有效期、安全码、摘要。
 *  卡号和安全码只在加卡时上传一次，列表里只有尾号。 */
export interface PaymentCard {
  id: string; label: string; brand: string; brand_name: string; last4: string; exp: string;
  exp_month: number; exp_year: number; holder: string; postal_code: string; expired: boolean;
  created_at: string | null; last_used_at: string | null;
}

export const BRAND_NAMES: Record<string, string> = {
  visa: "Visa", mastercard: "Mastercard", amex: "American Express", unionpay: "银联",
  jcb: "JCB", discover: "Discover", diners: "Diners Club", card: "银行卡",
};

export const cardDigits = (s: string) => s.replace(/\D/g, "");

export function cardBrand(input: string): string {
  const n = cardDigits(input);
  if (!n) return "card";
  const p = (k: number) => (n.length >= k ? Number(n.slice(0, k)) : -1);
  if (p(2) === 34 || p(2) === 37) return "amex";
  if (n.startsWith("4")) return "visa";
  if ((p(2) >= 51 && p(2) <= 55) || (p(4) >= 2221 && p(4) <= 2720)) return "mastercard";
  if (p(2) === 62) return "unionpay";
  if (p(4) >= 3528 && p(4) <= 3589) return "jcb";
  if (n.startsWith("6011") || p(2) === 65 || (p(3) >= 644 && p(3) <= 649)) return "discover";
  if (p(2) === 36 || p(2) === 38 || (p(3) >= 300 && p(3) <= 305)) return "diners";
  return "card";
}

export function groupCardNumber(input: string): string {
  const d = cardDigits(input);
  const sizes = cardBrand(d) === "amex" ? [4, 6, 5] : [4, 4, 4, 4, 4];
  const out: string[] = [];
  let i = 0;
  for (const n of sizes) { if (i >= d.length) break; out.push(d.slice(i, i + n)); i += n; }
  return out.join(" ");
}

export function luhnOk(input: string): boolean {
  const n = cardDigits(input);
  let total = 0;
  for (let i = 0; i < n.length; i++) {
    let d = Number(n[n.length - 1 - i]);
    if (i % 2) d = d > 4 ? d * 2 - 9 : d * 2;
    total += d;
  }
  return n.length > 0 && total % 10 === 0;
}

export function cardNumberError(input: string): string | null {
  const n = cardDigits(input);
  if (n.length < 12 || n.length > 19) return "卡号位数有误";
  if (cardBrand(n) !== "unionpay" && !luhnOk(n)) return "卡号校验没通过，可能抄错了一位";
  return null;
}

export function parseExpiry(s: string): [number, number] | null {
  const m = /^\s*(\d{1,2})\s*[/\-\s]?\s*(\d{2}|\d{4})\s*$/.exec(s);
  if (!m) return null;
  const month = Number(m[1]);
  let year = Number(m[2]);
  if (year < 100) year += 2000;
  return month >= 1 && month <= 12 ? [month, year] : null;
}

export function expiryError(s: string, now = new Date()): string | null {
  const e = parseExpiry(s);
  if (!e) return "有效期写成 月/年，比如 09/28";
  const y = now.getFullYear(), m = now.getMonth() + 1;
  if (e[1] < y || (e[1] === y && e[0] < m)) return "这张卡已经过期了";
  if (e[1] > y + 20) return "有效期年份有误";
  return null;
}

export function cvcError(s: string, brand: string): string | null {
  const c = s.trim(), want = brand === "amex" ? 4 : 3;
  const ok = /^\d+$/.test(c) && (brand === "card" ? c.length >= 3 && c.length <= 4 : c.length === want);
  return ok ? null : `安全码是卡背面的 ${want} 位数字`;
}

/** 有效期输入：只留数字、最多 4 位，满 3 位插 “/”；首位 2–9 自动补 0。deleting = 用户在删字（不再自动补回 “/”）。 */
export function formatExpiry(text: string, deleting: boolean): string {
  let d = cardDigits(text);
  if (d.length === 1 && Number(d) > 1) d = `0${d}`;
  d = d.slice(0, 4);
  return d.length > 2 || (d.length === 2 && !deleting) ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
}

/** 卡面上的卡号：输入了的显示数字，其余补 •（16 位，运通 15 位）。 */
export function maskedNumber(input: string, brand: string): string {
  const d = cardDigits(input);
  const total = brand === "amex" ? 15 : Math.max(16, d.length);
  let seen = 0;
  return groupCardNumber(d.padEnd(total, "0")).split("").map((ch) => (ch === " " ? " " : seen++ < d.length ? ch : "•")).join("");
}

export const cardLine = (c: PaymentCard) => `${c.brand_name} •••• ${c.last4} · 有效期 ${c.exp}`;

export function walletSummary(cards: PaymentCard[]): string {
  if (!cards.length) return "还没有卡";
  const old = cards.filter((c) => c.expired).length;
  return `${cards.length} 张卡${old ? ` · ${old} 张已过期` : ""}`;
}
