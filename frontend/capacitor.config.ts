import type { CapacitorConfig } from "@capacitor/cli";

// 安卓壳：直接打包 dist/，首次打开在登录页填服务器地址
const config: CapacitorConfig = {
  appId: "com.personal.assistant",
  appName: "Assistant",
  webDir: "dist",
  android: { allowMixedContent: false },
};
export default config;
