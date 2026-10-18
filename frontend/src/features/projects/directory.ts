// v3.5.2 项目 = 目录（照 Hark，= App backToDirectory）：没有依赖，tests/directory.test.ts 直接跑。
/** v3.5.2 从项目目录进项目时带的路由状态：项目内 ☰ 看到它就退一页（= 浏览器返回）回目录，没有（深链 / 别处跳来）就去 /projects。 */
export const DIR_ENTRY = { fromDirectory: true } as const;
export const cameFromDirectory = (state: unknown) => !!(state && typeof state === "object" && (state as { fromDirectory?: boolean }).fromDirectory);
