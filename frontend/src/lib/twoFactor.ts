import { appName } from "../brand";
// 两步验证（v2.58，= App models/two_factor.dart）：/api/auth/2fa* 的数据和文字规则。规则本身在后端 app/two_factor.py。

export interface TwoFactorStatus { enabled: boolean; enabled_at: string | null; recovery_left: number; pending: boolean }
export interface TwoFactorSetup { secret: string; uri: string; qr: string[]; account: string }

/** 恢复码剩得少了就提醒重新生成。 */
export const RECOVERY_LOW = 2;

export const twoFactorSummary = (s: TwoFactorStatus) => (s.enabled ? "两步验证已开" : "两步验证没开");

export function twoFactorRowSubtitle(s: TwoFactorStatus | null): string {
  if (!s) return "登录时多一道验证码";
  if (!s.enabled) return "没开 · 登录只要密码";
  return s.recovery_left <= RECOVERY_LOW ? `已开 · 恢复码只剩 ${s.recovery_left} 个` : "已开 · 登录要验证码";
}

export function recoveryLine(left: number): string {
  if (left === 0) return "恢复码用完了，重新生成一组";
  if (left <= RECOVERY_LOW) return `只剩 ${left} 个，建议重新生成`;
  return `还剩 ${left} 个，每个只能用一次`;
}

export const recoveryCodesText = (codes: string[], account = "") =>
  [`${appName} 两步验证恢复码${account ? `（${account}）` : ""}`, "每个只能用一次；手机丢了时代替验证码登录。", "", ...codes].join("\n");

/** 去空格/下划线、全角数字转半角；6 位数字 = 验证码，其余按恢复码交给服务器。 */
export const cleanCode = (raw: string) =>
  raw.trim().replace(/[０-９]/g, (c) => String(c.charCodeAt(0) - 0xff10)).replace(/[\s_]/g, "");

export const looksLikeTotp = (raw: string) => /^\d{6}$/.test(cleanCode(raw));

/** 二维码能画：方阵、只有 0/1。 */
export const qrDrawable = (rows: string[]) => rows.length > 0 && rows.every((r) => r.length === rows.length && /^[01]+$/.test(r));

/** 模块矩阵 → 一条 SVG path（每个黑块一个 h1v1 方格），四周留白 quiet 个模块。 */
export function qrPath(rows: string[], quiet = 2): string {
  let d = "";
  rows.forEach((r, y) => { for (let x = 0; x < r.length; x++) if (r[x] === "1") d += `M${x + quiet} ${y + quiet}h1v1h-1z`; });
  return d;
}
