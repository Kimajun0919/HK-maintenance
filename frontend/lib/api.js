const AUTH_KEY = "hk.authToken";

const withAuth = (options = {}) => {
  const token = localStorage.getItem(AUTH_KEY) || "";
  const headers = new Headers(options.headers || {});
  if (token && !headers.has("X-HK-Auth")) headers.set("X-HK-Auth", token);
  return { ...options, headers };
};

const readResponse = async (res) => {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
};

export const authFetch = async (path, options) => {
  let res = await fetch(path, withAuth(options));
  if (res.status === 401) {
    const token = window.prompt("관리자 접근 토큰을 입력하세요.");
    if (token) {
      localStorage.setItem(AUTH_KEY, token.trim());
      res = await fetch(path, withAuth(options));
    }
  }
  return res;
};

export const api = (path, options) => authFetch(path, options).then(async (res) => {
  const data = await readResponse(res);
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
});
