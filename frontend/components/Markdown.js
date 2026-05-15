import { h } from "../shared/react.js";
import { renderMarkdown } from "../lib/markdown.js";

export function Markdown({ text, source = "", className = "markdown" }) {
  return h("div", { className, dangerouslySetInnerHTML: { __html: renderMarkdown(text, source) } });
}
