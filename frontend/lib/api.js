const readResponse = async (res) => {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
};

export const authFetch = (path, options = {}) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 60000);
  return fetch(path, { ...options, signal: options.signal || controller.signal })
    .finally(() => clearTimeout(timeout))
    .catch((err) => {
      if (err && err.name === "AbortError") {
        throw new Error("요청 시간이 초과되었습니다. 서버 상태를 확인해 주세요.");
      }
      throw err;
    });
};

export const api = (path, options) => authFetch(path, options).then(async (res) => {
  const data = await readResponse(res);
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
});
