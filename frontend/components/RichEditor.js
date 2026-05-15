import { React, h } from "../shared/react.js";

export function RichEditor({ value, source, onChange, minHeight = "520px", maxSizeBytes = 2 * 1024 * 1024 }) {
  const hostRef = React.useRef(null);
  const editorRef = React.useRef(null);
  const sourceRef = React.useRef(source);
  const onChangeRef = React.useRef(onChange);
  const maxSizeBytesRef = React.useRef(maxSizeBytes);

  React.useEffect(() => { sourceRef.current = source; }, [source]);
  React.useEffect(() => { onChangeRef.current = onChange; }, [onChange]);
  React.useEffect(() => { maxSizeBytesRef.current = maxSizeBytes; }, [maxSizeBytes]);

  React.useEffect(() => {
    if (!hostRef.current || !window.toastui || !window.toastui.Editor) return;
    const editor = new window.toastui.Editor({
      el: hostRef.current,
      initialValue: value || "",
      initialEditType: "wysiwyg",
      previewStyle: "vertical",
      height: minHeight,
      hideModeSwitch: true,
      usageStatistics: false,
      toolbarItems: [
        ["heading", "bold", "italic", "strike"],
        ["hr", "quote"],
        ["ul", "ol", "task"],
        ["table", "image", "link"],
        ["code", "codeblock"]
      ],
      hooks: {
        addImageBlobHook: async (blob, callback) => {
          try {
            if (blob.size > maxSizeBytesRef.current) {
              const mb = (maxSizeBytesRef.current / 1024 / 1024).toFixed(0);
              throw new Error(`파일이 너무 큽니다. 최대 ${mb}MB까지 업로드할 수 있습니다.`);
            }
            const form = new FormData();
            form.append("source", sourceRef.current || "");
            form.append("file", blob, blob.name || "image.png");
            const res = await fetch("/api/asset", { method: "POST", body: form });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || res.statusText);
            callback(data.url, blob.name || "image");
          } catch (err) {
            alert(err.message || "이미지 업로드에 실패했습니다.");
          }
        }
      },
      events: {
        change: () => onChangeRef.current(editor.getMarkdown())
      }
    });
    editorRef.current = editor;
    return () => {
      editor.destroy();
      editorRef.current = null;
    };
  }, [minHeight]);

  React.useEffect(() => {
    const editor = editorRef.current;
    if (editor && value !== editor.getMarkdown()) {
      editor.setMarkdown(value || "", false);
    }
  }, [value]);

  return h("div", { className: "rich-editor", ref: hostRef });
}
