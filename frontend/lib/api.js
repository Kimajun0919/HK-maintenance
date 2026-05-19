const readResponse = async (res) => {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
};

export const authFetch = (path, options) => fetch(path, options);

export const api = (path, options) => authFetch(path, options).then(async (res) => {
  const data = await readResponse(res);
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
});
