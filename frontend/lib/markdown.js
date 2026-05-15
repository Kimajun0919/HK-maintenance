export const escapeHtml = (value) => String(value || "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;")
  .replace(/'/g, "&#39;");

export const assetUrl = (url, baseSource) => {
  if (/^(https?:)?\/\//i.test(url) || url.startsWith("data:") || url.startsWith("/")) return url;
  if (!baseSource) return url;
  return "/api/asset?source=" + encodeURIComponent(baseSource) + "&path=" + encodeURIComponent(url);
};

export const inlineMarkdown = (value, baseSource = "") => {
  let text = escapeHtml(value);
  text = text.replace(/!\[([^\]]*)\]\((.+)\)/g, (_match, alt, rawUrl) => {
    const cleanUrl = rawUrl.trim().replace(/\s+&quot;[^&]*&quot;$/, "");
    return `<img src="${assetUrl(cleanUrl, baseSource)}" alt="${alt}" loading="lazy" />`;
  });
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  text = text.replace(/(^|[\s(])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noreferrer">$2</a>');
  return text;
};

export const renderMarkdown = (source, baseSource = "") => {
  const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let i = 0;

  const tableRow = (line, tag) => {
    const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
    return "<tr>" + cells.map((cell) => `<${tag}>${inlineMarkdown(cell.trim(), baseSource)}</${tag}>`).join("") + "</tr>";
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2], baseSource)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      html.push("<hr />");
      i += 1;
      continue;
    }

    if (trimmed.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
      html.push("<table><thead>" + tableRow(trimmed, "th") + "</thead><tbody>");
      i += 2;
      while (i < lines.length && lines[i].trim().includes("|")) {
        html.push(tableRow(lines[i], "td"));
        i += 1;
      }
      html.push("</tbody></table>");
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      html.push("<ul>");
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        html.push(`<li>${inlineMarkdown(lines[i].trim().replace(/^[-*]\s+/, ""), baseSource)}</li>`);
        i += 1;
      }
      html.push("</ul>");
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      html.push("<ol>");
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        html.push(`<li>${inlineMarkdown(lines[i].trim().replace(/^\d+\.\s+/, ""), baseSource)}</li>`);
        i += 1;
      }
      html.push("</ol>");
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quote.push(lines[i].trim().replace(/^>\s?/, ""));
        i += 1;
      }
      html.push(`<blockquote>${inlineMarkdown(quote.join(" "), baseSource)}</blockquote>`);
      continue;
    }

    const paragraph = [trimmed];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,3})\s+/.test(lines[i].trim()) &&
      !/^([-*]|\d+\.)\s+/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith("```")
    ) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    html.push(`<p>${inlineMarkdown(paragraph.join(" "), baseSource)}</p>`);
  }

  return html.join("");
};
