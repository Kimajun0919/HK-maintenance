export const api = (path, options) => fetch(path, options).then(async (res) => {
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
});
