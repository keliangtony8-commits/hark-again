/** 唯一的 HTTP 出口。服务器地址可配置（安卓 App 里不是同源）。 */
const TOKEN_KEY = "assistant.token";
const SERVER_KEY = "assistant.server";

export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export const server = {
  get: () => localStorage.getItem(SERVER_KEY) ?? "",
  set: (url: string) => localStorage.setItem(SERVER_KEY, url.replace(/\/+$/, "")),
  wsUrl: (path: string) => {
    const base = server.get() || location.origin;
    return base.replace(/^http/, "ws") + path;
  },
};

let unauthorizedHandler = () => {};
export const onUnauthorized = (fn: () => void) => { unauthorizedHandler = fn; };
export const notifyUnauthorized = () => unauthorizedHandler();

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(server.get() + path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.get() ?? ""}`, ...init.headers },
  });
  if (res.status === 401) { notifyUnauthorized(); throw new Error("未登录"); }
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))).detail; // 字符串，或 {message, …}（如撤销冲突 {reason, message, conflicts}）
    throw new Error((typeof d === "string" ? d : d?.message) ?? res.statusText);
  }
  return res.json();
}

export const http = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body: unknown) => request<T>(p, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(p: string, body: unknown) => request<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  del: (p: string) => request(p, { method: "DELETE" }),
  upload,
  postBlob,
};

/** 返回二进制的 POST（朗读的 mp3）。错误照常按 {detail} 抛出。 */
async function postBlob(path: string, body: unknown): Promise<Blob> {
  const res = await fetch(server.get() + path, {
    method: "POST", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.get() ?? ""}` },
  });
  if (res.status === 401) { notifyUnauthorized(); throw new Error("未登录"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.blob();
}

/** 上传文件（multipart，不能设 Content-Type，让浏览器自己带 boundary）。 */
async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(server.get() + path, { method: "POST", body: form, headers: { Authorization: `Bearer ${auth.get() ?? ""}` } });
  if (res.status === 401) { notifyUnauthorized(); throw new Error("未登录"); }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

/** <img>/<a> 无法带请求头，下载地址用 ?token= 鉴权。 */
export const fileUrl = (path: string) => `${server.get()}${path}?token=${encodeURIComponent(auth.get() ?? "")}`;

export const api = {
  login: (username: string, password: string) => http.post<{ token: string }>("/api/auth/login", { username, password }),
};
