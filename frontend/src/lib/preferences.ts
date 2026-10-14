// 偏好设置（v2.67，= App models/preferences.dart）：/api/preferences。现在只有回复语言；规则在后端 app/reply_language.py，
// 选项和显示名由服务器给。

export interface LanguageChoice { code: string; label: string }
export interface Preferences { reply_language: string; reply_languages: LanguageChoice[] }

export const AUTO = "auto";

export const replyLanguageHint = (code: string) =>
  code === AUTO ? "我用什么语言说，就用什么语言回" : "不管我用什么语言说，都用它回；语音识别也跟着换";
