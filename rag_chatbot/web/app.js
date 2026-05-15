const h = React.createElement;

      const Icon = ({ name }) => {
        const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true" };
        if (name === "file-plus") {
          return h("svg", common,
            h("path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }),
            h("path", { d: "M14 2v6h6" }),
            h("path", { d: "M12 18v-6" }),
            h("path", { d: "M9 15h6" })
          );
        }
        if (name === "folder-plus") {
          return h("svg", common,
            h("path", { d: "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.2a2 2 0 0 1-1.6-.8L10.4 4A2 2 0 0 0 8.8 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z" }),
            h("path", { d: "M12 10v6" }),
            h("path", { d: "M9 13h6" })
          );
        }
        if (name === "folder") {
          return h("svg", common,
            h("path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" })
          );
        }
        if (name === "sort-asc") {
          return h("svg", common,
            h("line", { x1: 3, y1: 6, x2: 13, y2: 6 }),
            h("line", { x1: 3, y1: 12, x2: 10, y2: 12 }),
            h("line", { x1: 3, y1: 18, x2: 7, y2: 18 }),
            h("polyline", { points: "18 4 22 8 18 8" }),
            h("line", { x1: 22, y1: 8, x2: 22, y2: 20 })
          );
        }
        if (name === "sort-latest") {
          return h("svg", common,
            h("circle", { cx: 12, cy: 12, r: 10 }),
            h("polyline", { points: "12 6 12 12 16 14" })
          );
        }
        return null;
      };

      const api = (path, options) => fetch(path, options).then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        return data;
      });

      const escapeHtml = (value) => String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");

      const assetUrl = (url, baseSource) => {
        if (/^(https?:)?\/\//i.test(url) || url.startsWith("data:") || url.startsWith("/")) return url;
        if (!baseSource) return url;
        return "/api/asset?source=" + encodeURIComponent(baseSource) + "&path=" + encodeURIComponent(url);
      };

      const inlineMarkdown = (value, baseSource = "") => {
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

      const renderMarkdown = (source, baseSource = "") => {
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

      function Markdown({ text, source = "", className = "markdown" }) {
        return h("div", { className, dangerouslySetInnerHTML: { __html: renderMarkdown(text, source) } });
      }

      function RichEditor({ value, source, onChange, minHeight = "520px", maxSizeBytes = 2 * 1024 * 1024 }) {
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

      function App() {
        const [meta, setMeta] = React.useState(null);
        const [docs, setDocs] = React.useState([]);
        const [folders, setFolders] = React.useState([]);
        const [docFilter, setDocFilter] = React.useState("");
        const [docSort, setDocSort] = React.useState(() => localStorage.getItem("hk.docSort") || "asc");
        const [openFolders, setOpenFolders] = React.useState({});
        const [selected, setSelected] = React.useState("");
        const [doc, setDoc] = React.useState(null);
        const [editMode, setEditMode] = React.useState(false);
        const [draft, setDraft] = React.useState("");
        const [showCreate, setShowCreate] = React.useState(false);
        const [showFolderCreate, setShowFolderCreate] = React.useState(false);
        const [newFolderName, setNewFolderName] = React.useState("");
        const [folderPickerMode, setFolderPickerMode] = React.useState("");
        const [folderPickerNewName, setFolderPickerNewName] = React.useState("");
        const [renamingFolder, setRenamingFolder] = React.useState("");
        const [renameFolderName, setRenameFolderName] = React.useState("");
        const [showRenameDoc, setShowRenameDoc] = React.useState(false);
        const [renameDocFolder, setRenameDocFolder] = React.useState("");
        const [renameDocTitle, setRenameDocTitle] = React.useState("");
        const [newCustomer, setNewCustomer] = React.useState("");
        const [newTitle, setNewTitle] = React.useState("");
        const [newContent, setNewContent] = React.useState("");
        const [activeTool, setActiveTool] = React.useState("search");
        const [searchQuery, setSearchQuery] = React.useState("");
        const [search, setSearch] = React.useState(null);
        const [chatQuery, setChatQuery] = React.useState("");
        const [chatAnswer, setChatAnswer] = React.useState("");
        const [topK, setTopK] = React.useState(5);
        const [answerProvider, setAnswerProvider] = React.useState("local");
        const [claudeApiKey, setClaudeApiKey] = React.useState("");
        const [claudeModel, setClaudeModel] = React.useState("claude-sonnet-4-5");
        const [useLlm, setUseLlm] = React.useState(false);
        const [leftWidth, setLeftWidth] = React.useState(() => Number(localStorage.getItem("hk.leftWidth")) || 320);
        const [rightWidth, setRightWidth] = React.useState(() => Number(localStorage.getItem("hk.rightWidth")) || 360);
        const [leftCollapsed, setLeftCollapsed] = React.useState(() => localStorage.getItem("hk.leftCollapsed") === "1");
        const [rightCollapsed, setRightCollapsed] = React.useState(() => localStorage.getItem("hk.rightCollapsed") === "1");
        const [explorerMenu, setExplorerMenu] = React.useState(null);
        const [draggedDocSource, setDraggedDocSource] = React.useState("");
        const [draggedFolderName, setDraggedFolderName] = React.useState("");
        const [draggingSide, setDraggingSide] = React.useState("");
        const [loading, setLoading] = React.useState("");
        const [error, setError] = React.useState("");
        const [trashOpen, setTrashOpen] = React.useState(false);
        const [trashItems, setTrashItems] = React.useState(null);
        const [folderOrder, setFolderOrder] = React.useState(() => {
          try { return JSON.parse(localStorage.getItem("hk.folderOrder") || "null") || null; } catch { return null; }
        });
        const [pinnedFolders, setPinnedFolders] = React.useState(() => {
          try { return new Set(JSON.parse(localStorage.getItem("hk.pinnedFolders") || "[]")); } catch { return new Set(); }
        });
        const [dragOverFolder, setDragOverFolder] = React.useState("");
        const [folderManagerOpen, setFolderManagerOpen] = React.useState(false);
        const [fmRenaming, setFmRenaming] = React.useState("");
        const [fmRenameValue, setFmRenameValue] = React.useState("");
        const [fmCreating, setFmCreating] = React.useState(false);
        const [fmNewName, setFmNewName] = React.useState("");
        const [fmDragFrom, setFmDragFrom] = React.useState("");
        const [fmDragOver, setFmDragOver] = React.useState("");
        const [fmSelectedFolder, setFmSelectedFolder] = React.useState(null);

        const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

        React.useEffect(() => {
          localStorage.setItem("hk.leftWidth", String(leftWidth));
        }, [leftWidth]);

        React.useEffect(() => {
          localStorage.setItem("hk.rightWidth", String(rightWidth));
        }, [rightWidth]);

        React.useEffect(() => {
          localStorage.setItem("hk.leftCollapsed", leftCollapsed ? "1" : "0");
        }, [leftCollapsed]);

        React.useEffect(() => {
          localStorage.setItem("hk.rightCollapsed", rightCollapsed ? "1" : "0");
        }, [rightCollapsed]);

        React.useEffect(() => {
          localStorage.setItem("hk.docSort", docSort);
        }, [docSort]);

        const startResize = (side, event) => {
          event.preventDefault();
          const startX = event.clientX;
          const startLeft = leftWidth;
          const startRight = rightWidth;
          setDraggingSide(side);

          const onMove = (moveEvent) => {
            const delta = moveEvent.clientX - startX;
            if (side === "left") {
              setLeftWidth(clamp(startLeft + delta, 240, 560));
            } else {
              setRightWidth(clamp(startRight - delta, 280, 620));
            }
          };

          const onUp = () => {
            setDraggingSide("");
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onUp);
          };

          document.addEventListener("pointermove", onMove);
          document.addEventListener("pointerup", onUp);
        };

        React.useEffect(() => {
          refreshMeta();
          loadDocs();
          loadTrash();
        }, []);

        const loadDocs = () => {
          return api("/api/docs").then((data) => {
            const list = data.docs || [];
            const folderList = data.folders || [];
            setDocs(list);
            setFolders(folderList);
            const firstFolders = {};
            (folderList.length ? folderList : list.slice(0, 1)).slice(0, 1).forEach((item) => {
              firstFolders[item.name || item.customer || "기타"] = true;
            });
            setOpenFolders((prev) => Object.keys(prev).length ? prev : firstFolders);
            return list;
          }).catch((err) => setError(err.message));
        };

        const refreshMeta = () => {
          return api("/api/meta").then((data) => {
            setMeta(data);
            if (data.claudeDefaultModel) setClaudeModel(data.claudeDefaultModel);
            return data;
          }).catch((err) => setError(err.message));
        };

        const groupedDocs = React.useMemo(() => {
          const q = docFilter.trim().toLowerCase();
          const groups = new Map();
          folders.forEach((folder) => {
            const name = folder.name || "기타";
            if (!groups.has(name)) groups.set(name, { folder, items: [] });
          });
          docs.forEach((item) => {
            const haystack = [item.title, item.customer, item.source].join(" ").toLowerCase();
            if (q && !haystack.includes(q)) return;
            const key = item.customer || "기타";
            if (!groups.has(key)) groups.set(key, { folder: { name: key, sortOrder: 9999 }, items: [] });
            groups.get(key).items.push(item);
          });
          const compareText = (a, b) => a.localeCompare(b, "ko");
          const compareLatest = (a, b) => {
            const ta = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
            const tb = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
            return tb - ta || compareText(a.title, b.title);
          };
          const entries = Array.from(groups.entries()).filter(([folder, group]) => {
            if (!q) return true;
            return folder.toLowerCase().includes(q) || group.items.length > 0;
          });
          entries.forEach(([, group]) => {
            if (docSort === "latest") group.items.sort(compareLatest);
            else group.items.sort((a, b) => compareText(a.title, b.title));
          });
          entries.sort((a, b) => {
            const ap = pinnedFolders.has(a[0]);
            const bp = pinnedFolders.has(b[0]);
            if (ap !== bp) return ap ? -1 : 1;
            if (docSort === "latest") {
              const ta = Math.max(...a[1].items.map((i) => i.updatedAt ? new Date(i.updatedAt).getTime() : 0), 0);
              const tb = Math.max(...b[1].items.map((i) => i.updatedAt ? new Date(i.updatedAt).getTime() : 0), 0);
              return tb - ta || compareText(a[0], b[0]);
            }
            if (folderOrder) {
              const ai = folderOrder.indexOf(a[0]);
              const bi = folderOrder.indexOf(b[0]);
              if (ai !== -1 && bi !== -1) return ai - bi;
              if (ai !== -1) return -1;
              if (bi !== -1) return 1;
            }
            return compareText(a[0], b[0]);
          });
          return entries.map(([folder, group]) => [folder, group.items, group.folder]);
        }, [docs, folders, docFilter, docSort]);

        const openDoc = (source) => {
          setSelected(source);
          setEditMode(false);
          setShowCreate(false);
          setLoading("doc");
          setError("");
          api("/api/doc?source=" + encodeURIComponent(source))
            .then((data) => {
              setDoc(data);
              setDraft(data.content || "");
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const toggleFolder = (folder) => {
          setOpenFolders((prev) => ({ ...prev, [folder]: !prev[folder] }));
        };

        const openFolderPicker = (mode) => {
          setFolderPickerMode(mode);
          setFolderPickerNewName("");
        };

        const closeFolderPicker = () => {
          setFolderPickerMode("");
          setFolderPickerNewName("");
        };

        const chooseFolder = (name) => {
          if (folderPickerMode === "new-doc") setNewCustomer(name);
          if (folderPickerMode === "rename-doc") setRenameDocFolder(name);
          setOpenFolders((prev) => ({ ...prev, [name]: true }));
          closeFolderPicker();
        };

        const createFolderFromPicker = (event) => {
          event && event.preventDefault();
          const name = folderPickerNewName.trim();
          if (!name) return;
          setLoading("folder");
          setError("");
          api("/api/folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          })
            .then(() => {
              if (folderPickerMode === "new-doc") setNewCustomer(name);
              if (folderPickerMode === "rename-doc") setRenameDocFolder(name);
              setShowFolderCreate(false);
              setNewFolderName("");
              setOpenFolders((prev) => ({ ...prev, [name]: true }));
              closeFolderPicker();
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const createFolder = (event) => {
          event && event.preventDefault();
          if (!newFolderName.trim()) return;
          setLoading("folder");
          setError("");
          api("/api/folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newFolderName.trim() }),
          })
            .then(() => {
              const name = newFolderName.trim();
              setShowFolderCreate(false);
              setNewFolderName("");
              setOpenFolders((prev) => ({ ...prev, [name]: true }));
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const startRenameFolder = (folder) => {
          setRenamingFolder(folder);
          setRenameFolderName(folder);
        };

        const renameFolder = (event) => {
          event && event.preventDefault();
          if (!renamingFolder || !renameFolderName.trim()) return;
          setLoading("folder");
          setError("");
          api("/api/folder", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: renamingFolder, newName: renameFolderName.trim() }),
          })
            .then(() => {
              const oldName = renamingFolder;
              const newName = renameFolderName.trim();
              setRenamingFolder("");
              setRenameFolderName("");
              setOpenFolders((prev) => {
                const next = { ...prev, [newName]: prev[oldName] };
                delete next[oldName];
                return next;
              });
              if (doc && doc.source.startsWith(oldName + "/")) {
                const nextSource = newName + "/" + doc.source.slice(oldName.length + 1);
                openDoc(nextSource);
              }
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const deleteFolder = (folder) => {
          if (!confirm(`'${folder}' 폴더를 삭제할까요? 비어 있는 폴더만 삭제됩니다.`)) return;
          setLoading("folder");
          setError("");
          api("/api/folder", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: folder }),
          })
            .then(() => Promise.all([loadDocs(), refreshMeta()]))
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const startRenameDoc = () => {
          if (!doc) return;
          const parts = (doc.source || "").split("/");
          setRenameDocFolder(parts[0] || "");
          setRenameDocTitle(doc.title || "");
          setShowRenameDoc(true);
          setEditMode(false);
        };

        const renameDoc = (event) => {
          event && event.preventDefault();
          if (!doc || !renameDocFolder.trim() || !renameDocTitle.trim()) return;
          setLoading("rename");
          setError("");
          api("/api/doc/rename", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source: doc.source,
              folder: renameDocFolder.trim(),
              title: renameDocTitle.trim(),
            }),
          })
            .then((data) => {
              setDoc(data);
              setDraft(data.content || "");
              setSelected(data.source);
              setShowRenameDoc(false);
              const folder = (data.source || "").split("/")[0] || "기타";
              setOpenFolders((prev) => ({ ...prev, [folder]: true }));
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const moveDocToFolder = (source, folder) => {
          const item = docs.find((entry) => entry.source === source);
          if (!item || !folder || item.customer === folder) return;
          setLoading("rename");
          setError("");
          api("/api/doc/rename", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source, folder, title: item.title }),
          })
            .then((data) => {
              if (doc && doc.source === source) {
                setDoc(data);
                setDraft(data.content || "");
                setSelected(data.source);
              }
              setOpenFolders((prev) => ({ ...prev, [folder]: true }));
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => {
              setDraggedDocSource("");
              setLoading("");
            });
        };

        const reorderFolder = (targetFolder) => {
          setDragOverFolder("");
          if (!draggedFolderName || draggedFolderName === targetFolder) return;
          const names = groupedDocs.map(([folder]) => folder);
          const from = names.indexOf(draggedFolderName);
          const to = names.indexOf(targetFolder);
          if (from < 0 || to < 0) return;
          names.splice(to, 0, names.splice(from, 1)[0]);
          setFolderOrder(names);
          localStorage.setItem("hk.folderOrder", JSON.stringify(names));
          setDraggedFolderName("");
        };

        const togglePinFolder = (folder) => {
          setPinnedFolders((prev) => {
            const next = new Set(prev);
            if (next.has(folder)) next.delete(folder); else next.add(folder);
            localStorage.setItem("hk.pinnedFolders", JSON.stringify([...next]));
            return next;
          });
        };

        const fmSubmitRename = (event) => {
          event && event.preventDefault();
          const newName = fmRenameValue.trim();
          if (!fmRenaming || !newName) { setFmRenaming(""); return; }
          const oldName = fmRenaming;
          setLoading("folder");
          api("/api/folder", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: oldName, newName }),
          })
            .then(() => {
              setFmRenaming(""); setFmRenameValue("");
              setOpenFolders((prev) => { const n = { ...prev, [newName]: prev[oldName] }; delete n[oldName]; return n; });
              setPinnedFolders((prev) => {
                if (!prev.has(oldName)) return prev;
                const n = new Set(prev); n.delete(oldName); n.add(newName);
                localStorage.setItem("hk.pinnedFolders", JSON.stringify([...n])); return n;
              });
              setFolderOrder((prev) => {
                if (!prev) return prev;
                const n = prev.map((x) => x === oldName ? newName : x);
                localStorage.setItem("hk.folderOrder", JSON.stringify(n)); return n;
              });
              if (doc && doc.source.startsWith(oldName + "/"))
                openDoc(newName + "/" + doc.source.slice(oldName.length + 1));
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const fmSubmitCreate = (event) => {
          event && event.preventDefault();
          const name = fmNewName.trim();
          if (!name) { setFmCreating(false); return; }
          setLoading("folder");
          api("/api/folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          })
            .then(() => { setFmNewName(""); setFmCreating(false); return Promise.all([loadDocs(), refreshMeta()]); })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const fmReorder = (targetFolder) => {
          setFmDragOver("");
          if (!fmDragFrom || fmDragFrom === targetFolder) { setFmDragFrom(""); return; }
          const names = groupedDocs.map(([f]) => f);
          const from = names.indexOf(fmDragFrom);
          const to = names.indexOf(targetFolder);
          if (from < 0 || to < 0) { setFmDragFrom(""); return; }
          names.splice(to, 0, names.splice(from, 1)[0]);
          setFolderOrder(names);
          localStorage.setItem("hk.folderOrder", JSON.stringify(names));
          setFmDragFrom("");
        };

        const runSearch = (event) => {
          event && event.preventDefault();
          const term = searchQuery.trim();
          if (!term) return;
          setLoading("search");
          setError("");
          api("/api/search?q=" + encodeURIComponent(term) + "&top_k=" + topK)
            .then(setSearch)
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const askChat = (event) => {
          event && event.preventDefault();
          const term = chatQuery.trim();
          if (!term) return;
          setLoading("chat");
          setError("");
          api("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query: term,
              topK,
              provider: answerProvider,
              apiKey: answerProvider === "claude" ? claudeApiKey : "",
              model: answerProvider === "claude" ? claudeModel : "",
            }),
          })
            .then((data) => setChatAnswer(data.answer || ""))
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const startCreate = () => {
          setShowCreate(true);
          setEditMode(false);
          setDoc(null);
          setSelected("");
          setNewCustomer("");
          setNewTitle("");
          setNewContent("");
        };

        const draftSource = (folder, title) => {
          const safeFolder = (folder || "미분류").trim() || "미분류";
          const safeTitle = (title || "새 문서").trim() || "새 문서";
          return safeFolder + "/" + safeTitle + ".md";
        };

        const createDoc = (event) => {
          event && event.preventDefault();
          if (!newTitle.trim()) {
            setError("문서 제목을 입력하세요.");
            return;
          }
          setLoading("save");
          setError("");
          api("/api/doc", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              customer: newCustomer.trim() || "미분류",
              title: newTitle.trim(),
              content: newContent,
            }),
          })
            .then((data) => {
              setShowCreate(false);
              setDoc(data);
              setDraft(data.content || "");
              setSelected(data.source);
              setEditMode(false);
              const folder = (data.source || "").split("/")[0] || "기타";
              setOpenFolders((prev) => ({ ...prev, [folder]: true }));
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const saveDoc = () => {
          if (!doc || !draft.trim()) return;
          setLoading("save");
          setError("");
          api("/api/doc", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: doc.source, content: draft }),
          })
            .then((data) => {
              setDoc(data);
              setDraft(data.content || "");
              setEditMode(false);
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const startRenameDocItem = (item) => {
          setDoc((prev) => prev && prev.source === item.source ? prev : { source: item.source, title: item.title, content: "" });
          setSelected(item.source);
          setRenameDocFolder(item.customer || "");
          setRenameDocTitle(item.title || "");
          setShowRenameDoc(true);
          setEditMode(false);
        };

        const deleteDocItem = (item) => {
          if (!confirm("문서를 휴지통으로 이동합니다.")) return;
          setLoading("delete");
          setError("");
          api("/api/doc", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: item.source }),
          })
            .then(() => {
              if (doc && doc.source === item.source) {
                setDoc(null);
                setDraft("");
                setSelected("");
                setEditMode(false);
              }
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const deleteDoc = () => {
          if (!doc) return;
          if (!confirm("문서를 휴지통으로 이동합니다. 30일 후 자동 영구 삭제됩니다.")) return;
          setLoading("delete");
          setError("");
          api("/api/doc", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: doc.source }),
          })
            .then(() => {
              setDoc(null);
              setDraft("");
              setSelected("");
              setEditMode(false);
              return Promise.all([loadDocs(), refreshMeta()]);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const loadTrash = () => {
          return api("/api/trash").then(setTrashItems).catch((err) => setError(err.message));
        };

        const openTrash = () => {
          setTrashOpen(true);
          loadTrash();
        };

        const restoreItem = (type, key) => {
          setLoading("trash");
          api("/api/trash/restore", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type, key }),
          })
            .then(() => Promise.all([loadTrash(), type === "doc" ? loadDocs() : Promise.resolve()]))
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const permanentDeleteItem = (type, key) => {
          if (!confirm("영구 삭제합니다. 복원할 수 없습니다.")) return;
          setLoading("trash");
          api("/api/trash", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type, key }),
          })
            .then(() => loadTrash())
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const emptyTrash = () => {
          if (!confirm("휴지통을 비웁니다. 모든 항목이 영구 삭제됩니다.")) return;
          setLoading("trash");
          api("/api/trash", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: "all" }),
          })
            .then(() => loadTrash())
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const deleteAsset = (assetPath) => {
          if (!confirm(`이미지를 휴지통으로 이동합니다.\n${assetPath.split("/").pop()}`)) return;
          api("/api/asset", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: assetPath }),
          })
            .then(() => doc && openDoc(doc.source))
            .catch((err) => setError(err.message));
        };

        const extractDocImages = (source, content) => {
          const folder = source.split("/").slice(0, -1).join("/");
          const images = [];
          const regex = /!\[([^\]]*)\]\(([^)]+)\)/g;
          let match;
          while ((match = regex.exec(content)) !== null) {
            const rawPath = match[2].trim().split(/\s+/)[0];
            if (rawPath.startsWith("http") || rawPath.startsWith("data:") || rawPath.startsWith("/")) continue;
            const dbPath = folder ? `${folder}/${rawPath}` : rawPath;
            const url = `/api/asset?source=${encodeURIComponent(source)}&path=${encodeURIComponent(rawPath)}`;
            images.push({ alt: match[1], rawPath, dbPath, url });
          }
          return images;
        };

        const trashDaysLeft = (deletedAt) => {
          const ms = 30 * 24 * 60 * 60 * 1000 - (Date.now() - new Date(deletedAt).getTime());
          return Math.max(0, Math.ceil(ms / (24 * 60 * 60 * 1000)));
        };

        const appStyle = {
          "--left-width": leftCollapsed ? "0px" : leftWidth + "px",
          "--right-width": rightCollapsed ? "0px" : rightWidth + "px",
          "--left-resizer-width": leftCollapsed ? "0px" : "6px",
          "--right-resizer-width": rightCollapsed ? "0px" : "6px",
        };

        return h("div", {
          className: "app " + (leftCollapsed ? "left-collapsed " : "") + (rightCollapsed ? "right-collapsed" : ""),
          style: appStyle,
          onClick: () => explorerMenu && setExplorerMenu(null)
        },
          folderManagerOpen && h("div", { className: "modal-backdrop", onMouseDown: () => { setFolderManagerOpen(false); setFmRenaming(""); setFmCreating(false); setFmSelectedFolder(null); } },
            h("section", { className: "fm-modal", onMouseDown: (e) => e.stopPropagation() },

              h("header", { className: "fm-header" },
                h("div", { className: "fm-title" },
                  fmSelectedFolder
                    ? [
                        h("button", { key: "back", type: "button", className: "fm-back-btn", onClick: () => { setFmSelectedFolder(null); setFmRenaming(""); } }, "←"),
                        h(Icon, { key: "icon", name: "folder" }),
                        h("span", { key: "slash", className: "fm-breadcrumb-sep" }, "/"),
                        h("strong", { key: "name" }, fmSelectedFolder)
                      ]
                    : [
                        h(Icon, { key: "icon", name: "folder" }),
                        h("strong", { key: "title" }, "폴더 관리"),
                        h("span", { key: "count", className: "fm-subtitle" }, `${folders.length}개`)
                      ]
                ),
                h("button", { type: "button", className: "icon-button", onClick: () => { setFolderManagerOpen(false); setFmSelectedFolder(null); } }, "×")
              ),

              h("div", { className: "fm-toolbar" },
                fmSelectedFolder
                  ? [
                      h("button", { key: "newfile", type: "button", className: "fm-new-btn", onClick: () => { setFolderManagerOpen(false); setFmSelectedFolder(null); startCreate(); setNewCustomer(fmSelectedFolder); } }, "+ 새 파일"),
                      h("span", { key: "count", className: "fm-toolbar-count" }, `파일 ${(groupedDocs.find(([f]) => f === fmSelectedFolder) || [null, []])[1].length}개`)
                    ]
                  : h("button", { type: "button", className: "fm-new-btn", onClick: () => { setFmCreating(true); setFmNewName(""); setFmRenaming(""); } }, "+ 새 폴더")
              ),

              fmSelectedFolder
                ? h("div", { className: "fm-body" },
                    (() => {
                      const fileItems = (groupedDocs.find(([f]) => f === fmSelectedFolder) || [null, []])[1];
                      if (fileItems.length === 0)
                        return h("div", { className: "fm-empty" }, "이 폴더에 파일이 없습니다.");
                      return fileItems.map((item) =>
                        h("div", {
                          key: item.source,
                          className: "fm-card fm-file-card",
                          onClick: () => { openDoc(item.source); setFolderManagerOpen(false); setFmSelectedFolder(null); }
                        },
                          h("div", { className: "fm-card-icon" },
                            h("svg", { width: 44, height: 44, viewBox: "0 0 24 24", fill: "#e0f2fe", stroke: "#38bdf8", strokeWidth: 1, "aria-hidden": "true" },
                              h("path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }),
                              h("path", { d: "M14 2v6h6" })
                            )
                          ),
                          h("span", { className: "fm-card-name", title: item.title }, item.title),
                          item.updatedAt && h("span", { className: "fm-card-count" }, new Date(item.updatedAt).toLocaleDateString("ko")),
                          h("div", { className: "fm-card-actions", onClick: (e) => e.stopPropagation() },
                            h("button", { type: "button", onClick: (e) => { e.stopPropagation(); setFolderManagerOpen(false); setFmSelectedFolder(null); startRenameDocItem(item); } }, "이름"),
                            h("button", { type: "button", className: "danger-text", onClick: (e) => { e.stopPropagation(); deleteDocItem(item); } }, "삭제")
                          )
                        )
                      );
                    })()
                  )
                : h("div", { className: "fm-body" },
                    groupedDocs.map(([folderName, items]) => {
                      const isPinned = pinnedFolders.has(folderName);
                      const isRenaming = fmRenaming === folderName;
                      return h("div", {
                        key: folderName,
                        className: "fm-card" + (isPinned ? " fm-pinned" : "") + (fmDragOver === folderName ? " fm-drag-over" : "") + (fmDragFrom === folderName ? " fm-dragging" : ""),
                        onClick: () => { if (!isRenaming && !fmDragFrom) setFmSelectedFolder(folderName); },
                        onDragOver: (e) => { e.preventDefault(); if (fmDragFrom && fmDragFrom !== folderName) setFmDragOver(folderName); },
                        onDragLeave: () => setFmDragOver(""),
                        onDrop: (e) => { e.preventDefault(); fmReorder(folderName); }
                      },
                        h("div", { className: "fm-card-top" },
                          h("span", {
                            className: "fm-card-drag",
                            draggable: true,
                            title: "드래그하여 순서 변경",
                            onClick: (e) => e.stopPropagation(),
                            onDragStart: (e) => { e.stopPropagation(); setFmDragFrom(folderName); },
                            onDragEnd: () => { setFmDragFrom(""); setFmDragOver(""); }
                          }, "⠿")
                        ),
                        h("div", { className: "fm-card-icon" },
                          h("svg", { width: 48, height: 48, viewBox: "0 0 24 24", fill: isPinned ? "#f59e0b" : "#60a5fa", stroke: isPinned ? "#d97706" : "#3b82f6", strokeWidth: 1, "aria-hidden": "true" },
                            h("path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" })
                          ),
                          isPinned && h("span", { className: "fm-pin-badge" }, "📌")
                        ),
                        isRenaming
                          ? h("form", { className: "fm-rename-form", onSubmit: fmSubmitRename, onClick: (e) => e.stopPropagation() },
                              h("input", {
                                className: "fm-rename-input",
                                value: fmRenameValue,
                                onChange: (e) => setFmRenameValue(e.target.value),
                                autoFocus: true,
                                onBlur: fmSubmitRename,
                                onKeyDown: (e) => { if (e.key === "Escape") setFmRenaming(""); }
                              })
                            )
                          : h("span", {
                              className: "fm-card-name",
                              title: folderName,
                              onDoubleClick: (e) => { e.stopPropagation(); setFmRenaming(folderName); setFmRenameValue(folderName); }
                            }, folderName),
                        h("span", { className: "fm-card-count" }, `${items.length}개`),
                        h("div", { className: "fm-card-actions", onClick: (e) => e.stopPropagation() },
                          h("button", { type: "button", onClick: () => togglePinFolder(folderName) }, isPinned ? "고정 해제" : "고정"),
                          h("button", { type: "button", onClick: () => { setFmRenaming(folderName); setFmRenameValue(folderName); } }, "이름"),
                          h("button", { type: "button", className: "danger-text", onClick: () => deleteFolder(folderName) }, "삭제")
                        )
                      );
                    }),
                    fmCreating && h("div", { className: "fm-card fm-creating" },
                      h("div", { className: "fm-card-icon" },
                        h("svg", { width: 48, height: 48, viewBox: "0 0 24 24", fill: "#e2e8f0", stroke: "#94a3b8", strokeWidth: 1, "aria-hidden": "true" },
                          h("path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" })
                        )
                      ),
                      h("form", { className: "fm-rename-form", onSubmit: fmSubmitCreate },
                        h("input", {
                          className: "fm-rename-input",
                          value: fmNewName,
                          placeholder: "폴더명",
                          onChange: (e) => setFmNewName(e.target.value),
                          autoFocus: true,
                          onBlur: () => { if (!fmNewName.trim()) setFmCreating(false); else fmSubmitCreate(); },
                          onKeyDown: (e) => { if (e.key === "Escape") { setFmCreating(false); setFmNewName(""); } }
                        })
                      )
                    ),
                    groupedDocs.length === 0 && !fmCreating && h("div", { className: "fm-empty" }, "폴더가 없습니다.")
                  )
            )
          ),

          folderPickerMode && h("div", { className: "modal-backdrop", onMouseDown: closeFolderPicker },
            h("section", { className: "folder-modal", onMouseDown: (event) => event.stopPropagation() },
              h("header", null,
                h("strong", null, folderPickerMode === "sidebar" ? "새 폴더" : "폴더 선택"),
                h("button", { type: "button", className: "icon-button", onClick: closeFolderPicker }, "x")
              ),
              folderPickerMode !== "sidebar" && h("div", { className: "folder-picker-list" },
                folders.map((folder) => h("button", {
                  key: folder.name,
                  type: "button",
                  className: "folder-choice",
                  onClick: () => chooseFolder(folder.name)
                },
                  h("strong", null, folder.name),
                  h("span", null, `${folder.docCount || 0} documents`)
                ))
              ),
              h("form", { className: "folder-create-row", onSubmit: createFolderFromPicker },
                h("input", {
                  value: folderPickerNewName,
                  onChange: (event) => setFolderPickerNewName(event.target.value),
                  placeholder: "새 폴더명"
                }),
                h("button", { type: "submit", className: "primary" }, loading === "folder" ? "생성 중" : "생성")
              )
            )
          ),
          h("nav", { className: "side-rail left-rail", "aria-label": "왼쪽 메뉴" },
            h("button", {
              type: "button",
              className: "rail-button " + (!leftCollapsed ? "active" : ""),
              title: leftCollapsed ? "자료 목록 펼치기" : "자료 목록 접기",
              onClick: () => setLeftCollapsed((value) => !value)
            }, "☰"),
            h("button", {
              type: "button",
              className: "rail-button",
              title: "자료 목록 폭 초기화",
              onClick: () => setLeftWidth(320)
            }, "↔"),
            h("div", { className: "rail-spacer" })
          ),
          h("aside", { className: "left-sidebar" },
            h("div", { className: "brand explorer-head" },
              h("div", { className: "panel-title-row" },
                h("h1", null, "Explorer"),
                h("div", { className: "panel-actions" },
                  h("button", {
                    type: "button",
                    className: "icon-button",
                    title: "왼쪽 사이드바 접기",
                    onClick: () => setLeftCollapsed(true)
                  }, "‹")
                )
              ),
              h("p", null, "자료를 폴더별로 열고 가운데에서 바로 확인")
            ),
            h("div", { className: "stats" },
              h("span", null, "문서 ", h("b", null, meta ? meta.docCount : "-")),
              h("span", null, "청크 ", h("b", null, meta ? meta.chunkCount : "-")),
              meta && meta.assetTotalBytes > 0 && h("span", {
                title: `이미지 ${meta.assetCount}개 / 파일당 최대 ${(meta.assetMaxSizeBytes / 1024 / 1024).toFixed(0)}MB`
              }, "이미지 ", h("b", null, (meta.assetTotalBytes / 1024 / 1024).toFixed(1) + "MB"))
            ),
            h("div", { className: "list-filter" },
              h("input", {
                value: docFilter,
                onChange: (event) => setDocFilter(event.target.value),
                placeholder: "자료 목록 필터"
              }),
              h("div", { className: "explorer-action-row" },
                h("button", {
                  type: "button",
                  className: "icon-button explorer-action",
                  title: "홈 (선택 해제)",
                  onClick: () => {
                    setDoc(null); setSelected(""); setDraft(""); setEditMode(false);
                    setShowCreate(false); setShowRenameDoc(false); setTrashOpen(false);
                    setError("");
                  }
                }, "⌂"),
                h("button", {
                  type: "button",
                  className: "icon-button explorer-action" + (folderManagerOpen ? " active" : ""),
                  title: "폴더 관리",
                  onClick: () => setFolderManagerOpen((v) => !v)
                }, h(Icon, { name: "folder" })),
                h("button", {
                  type: "button",
                  className: "icon-button explorer-action",
                  title: "새 문서",
                  onClick: startCreate
                }, h(Icon, { name: "file-plus" })),
                h("button", {
                  type: "button",
                  className: "icon-button explorer-action",
                  title: "새 폴더",
                  onClick: () => openFolderPicker("sidebar")
                }, h(Icon, { name: "folder-plus" })),
                h("div", { style: { position: "relative", display: "inline-flex" } },
                  h("button", {
                    type: "button",
                    className: "icon-button explorer-action" + (trashOpen ? " active" : ""),
                    title: "휴지통",
                    onClick: trashOpen ? () => setTrashOpen(false) : openTrash
                  }, "🗑"),
                  trashItems && (trashItems.docs.length + trashItems.assets.length) > 0 && h("span", { className: "trash-badge" },
                    trashItems.docs.length + trashItems.assets.length
                  )),
                h("div", { className: "sort-buttons" },
                  h("button", {
                    type: "button",
                    className: "icon-button explorer-action" + (docSort === "asc" ? " active" : ""),
                    title: "가나다순",
                    onClick: () => setDocSort("asc")
                  }, h(Icon, { name: "sort-asc" })),
                  h("button", {
                    type: "button",
                    className: "icon-button explorer-action" + (docSort === "latest" ? " active" : ""),
                    title: "최신순",
                    onClick: () => setDocSort("latest")
                  }, h(Icon, { name: "sort-latest" }))
                )
              ),
              showFolderCreate && h("form", { className: "inline-form", onSubmit: createFolder },
                h("input", {
                  value: newFolderName,
                  onChange: (event) => setNewFolderName(event.target.value),
                  placeholder: "새 폴더명"
                }),
                h("div", { className: "inline-actions" },
                  h("button", { type: "button", onClick: () => setShowFolderCreate(false) }, "취소"),
                  h("button", { type: "submit", className: "primary" }, loading === "folder" ? "생성 중" : "생성")
                )
              )
            ),
            trashOpen
              ? h("div", { className: "trash-panel" },
                  h("div", { className: "trash-header" },
                    h("span", null, "휴지통"),
                    trashItems && (trashItems.docs.length + trashItems.assets.length) > 0 && h("button", {
                      type: "button",
                      className: "trash-empty-btn",
                      onClick: emptyTrash,
                      disabled: loading === "trash"
                    }, "전체 비우기")
                  ),
                  !trashItems
                    ? h("div", { className: "empty" }, "불러오는 중...")
                    : trashItems.docs.length === 0 && trashItems.assets.length === 0
                      ? h("div", { className: "empty" }, "휴지통이 비었습니다.")
                      : h("div", null,
                          trashItems.docs.length > 0 && h("div", { className: "trash-section" },
                            h("div", { className: "trash-section-title" }, "문서"),
                            trashItems.docs.map((item) => h("div", { key: item.source, className: "trash-item" },
                              h("div", { className: "trash-item-info" },
                                h("strong", null, item.title),
                                h("span", null, `${trashDaysLeft(item.deleted_at)}일 후 영구삭제`)
                              ),
                              h("div", { className: "trash-item-actions" },
                                h("button", { type: "button", onClick: () => restoreItem("doc", item.source), disabled: loading === "trash" }, "복원"),
                                h("button", { type: "button", className: "danger-text", onClick: () => permanentDeleteItem("doc", item.source), disabled: loading === "trash" }, "영구삭제")
                              )
                            ))
                          ),
                          trashItems.assets.length > 0 && h("div", { className: "trash-section" },
                            h("div", { className: "trash-section-title" }, "이미지"),
                            trashItems.assets.map((item) => h("div", { key: item.path, className: "trash-item" },
                              h("div", { className: "trash-item-info" },
                                h("strong", null, item.path.split("/").pop()),
                                h("span", null, `${trashDaysLeft(item.deleted_at)}일 후 영구삭제`)
                              ),
                              h("div", { className: "trash-item-actions" },
                                h("button", { type: "button", onClick: () => restoreItem("asset", item.path), disabled: loading === "trash" }, "복원"),
                                h("button", { type: "button", className: "danger-text", onClick: () => permanentDeleteItem("asset", item.path), disabled: loading === "trash" }, "영구삭제")
                              )
                            ))
                          )
                        )
                )
              : h("div", { className: "folder-list" },
              groupedDocs.map(([folder, items]) => {
                const isOpen = !!openFolders[folder] || !!docFilter.trim();
                return h("div", { key: folder, className: "folder" },
                  renamingFolder === folder
                    ? h("form", { className: "folder-rename", onSubmit: renameFolder },
                        h("input", {
                          value: renameFolderName,
                          onChange: (event) => setRenameFolderName(event.target.value),
                          autoFocus: true
                        }),
                        h("button", { type: "button", onClick: () => setRenamingFolder("") }, "취소"),
                        h("button", { type: "submit", className: "primary" }, "저장")
                      )
                    : h("div", {
                        className: "folder-row" + (dragOverFolder === folder ? " drag-over" : ""),
                        onDragOver: (event) => { event.preventDefault(); if (draggedFolderName && draggedFolderName !== folder) setDragOverFolder(folder); },
                        onDragLeave: () => setDragOverFolder(""),
                        onDrop: (event) => {
                          event.preventDefault();
                          if (draggedDocSource) moveDocToFolder(draggedDocSource, folder);
                          else if (draggedFolderName) reorderFolder(folder);
                        }
                      },
                        h("button", {
                          className: "folder-toggle " + (isOpen ? "open" : ""),
                          onClick: () => toggleFolder(folder)
                        },
                          h("span", null, isOpen ? "▾" : "▸"),
                          h("strong", null, folder),
                          h("span", null, items.length),
                          pinnedFolders.has(folder) && h("span", { className: "pin-mark", title: "고정됨" }, "📌")
                        ),
                        h("button", {
                          type: "button",
                          className: "kebab-button",
                          title: "폴더 작업",
                          onClick: (event) => {
                            event.stopPropagation();
                            setExplorerMenu(explorerMenu && explorerMenu.type === "folder" && explorerMenu.id === folder ? null : { type: "folder", id: folder });
                          }
                        }, "..."),
                        explorerMenu && explorerMenu.type === "folder" && explorerMenu.id === folder && h("div", { className: "explorer-menu" },
                          h("button", { type: "button", onClick: () => { setExplorerMenu(null); togglePinFolder(folder); } },
                            pinnedFolders.has(folder) ? "📌 고정 해제" : "📌 고정하기"
                          ),
                          h("button", { type: "button", onClick: () => { setExplorerMenu(null); startCreate(); setNewCustomer(folder); } }, "새 문서"),
                          h("button", { type: "button", onClick: () => { setExplorerMenu(null); startRenameFolder(folder); } }, "이름 변경"),
                          h("button", { type: "button", className: "danger-text", onClick: () => { setExplorerMenu(null); deleteFolder(folder); } }, "삭제")
                        ),
                        docSort !== "latest" && h("span", {
                          className: "folder-drag-handle",
                          draggable: true,
                          title: "드래그하여 순서 변경",
                          onDragStart: (event) => { event.stopPropagation(); setDraggedFolderName(folder); },
                          onDragEnd: () => { setDraggedFolderName(""); setDragOverFolder(""); }
                        }, "⋮")
                      ),
                  isOpen && h("div", { className: "doc-group" },
                    items.map((item) => h("div", {
                      key: item.source,
                      className: "doc-item " + (selected === item.source ? "selected" : ""),
                      role: "button",
                      tabIndex: 0,
                      draggable: true,
                      onDragStart: (event) => {
                        event.stopPropagation();
                        setDraggedDocSource(item.source);
                      },
                      onDragEnd: () => setDraggedDocSource(""),
                      onClick: () => openDoc(item.source),
                      onKeyDown: (event) => { if (event.key === "Enter") openDoc(item.source); }
                    },
                      h("strong", null, item.title),
                      h("span", null, item.source),
                      h("i", {
                        className: "doc-menu-trigger",
                        onClick: (event) => {
                          event.stopPropagation();
                          setExplorerMenu(explorerMenu && explorerMenu.type === "doc" && explorerMenu.id === item.source ? null : { type: "doc", id: item.source });
                        }
                      }, "..."),
                      explorerMenu && explorerMenu.type === "doc" && explorerMenu.id === item.source && h("div", { className: "explorer-menu doc-menu" },
                        h("button", { type: "button", onClick: (event) => { event.stopPropagation(); setExplorerMenu(null); startRenameDocItem(item); } }, "이름 변경"),
                        h("button", { type: "button", className: "danger-text", onClick: (event) => { event.stopPropagation(); setExplorerMenu(null); deleteDocItem(item); } }, "삭제")
                      )
                    ))
                  )
                );
              }),
              groupedDocs.length === 0 && h("div", { className: "empty" }, "자료가 없습니다.")
            )
          ),


          h("div", {
            className: "resizer left-resizer " + (draggingSide === "left" ? "dragging" : ""),
            onPointerDown: (event) => startResize("left", event),
            title: "왼쪽 사이드바 폭 조절"
          }),

          h("main", { className: "main" },
            h("header", { className: "topbar" },
              h("div", { className: "topbar-title" },
                leftCollapsed && h("button", {
                  type: "button",
                  className: "icon-button",
                  title: "왼쪽 사이드바 펼치기",
                  onClick: () => setLeftCollapsed(false)
                }, "›"),
                h("strong", null, doc ? doc.title : "자료를 선택하세요")
              ),
              h("div", { className: "topbar-tools" },
                h("span", null, doc ? doc.source : "왼쪽 자료 목록 또는 오른쪽 검색을 사용하세요"),
                rightCollapsed && h("button", {
                  type: "button",
                  className: "icon-button",
                  title: "오른쪽 사이드바 펼치기",
                  onClick: () => setRightCollapsed(false)
                }, "‹")
              )
            ),
            h("section", { className: "reader" },
              error && h("p", { className: "error" }, error),
              chatAnswer && h("div", { className: "answer" }, h(Markdown, { text: chatAnswer })),
              showCreate && h("section", { className: "create-panel" },
                h("header", null, "새 문서 만들기"),
                h("form", { className: "create-form", onSubmit: createDoc },
                  h("div", { className: "form-grid" },
                    h("button", {
                      type: "button",
                      className: "folder-select",
                      onClick: () => openFolderPicker("new-doc")
                    },
                      h("span", null, "폴더"),
                      h("strong", null, newCustomer || "선택")
                    ),
                    h("input", {
                      value: newTitle,
                      onChange: (event) => setNewTitle(event.target.value),
                      placeholder: "문서 제목"
                    })
                  ),
                  h(RichEditor, {
                    value: newContent,
                    source: draftSource(newCustomer, newTitle),
                    onChange: setNewContent,
                    maxSizeBytes: meta ? meta.assetMaxSizeBytes : undefined,
                    minHeight: "480px"
                  }),
                  h("div", { className: "create-actions" },
                    h("button", { type: "button", onClick: () => setShowCreate(false) }, "취소"),
                    h("button", { type: "submit", className: "primary" }, loading === "save" ? "저장 중" : "생성")
                  )
                )
              ),
              showRenameDoc && doc && h("section", { className: "create-panel" },
                h("header", null, "파일명/폴더 수정"),
                h("form", { className: "create-form", onSubmit: renameDoc },
                  h("div", { className: "form-grid" },
                    h("button", {
                      type: "button",
                      className: "folder-select",
                      onClick: () => openFolderPicker("rename-doc")
                    },
                      h("span", null, "폴더"),
                      h("strong", null, renameDocFolder || "선택")
                    ),
                    h("input", {
                      value: renameDocTitle,
                      onChange: (event) => setRenameDocTitle(event.target.value),
                      placeholder: "파일명"
                    })
                  ),
                  h("div", { className: "create-actions" },
                    h("button", { type: "button", onClick: () => setShowRenameDoc(false) }, "취소"),
                    h("button", { type: "submit", className: "primary" }, loading === "rename" ? "저장 중" : "저장")
                  )
                )
              ),
              doc ? h("article", { className: "doc-view" },
                h("div", { className: "doc-header" },
                  h("div", { className: "doc-header-row" },
                    h("div", null,
                      h("div", { className: "path" }, doc.source),
                      h("h2", null, doc.title)
                    ),
                    h("div", { className: "doc-actions" },
                      editMode ? [
                        h("button", { key: "cancel", type: "button", onClick: () => { setDraft(doc.content || ""); setEditMode(false); } }, "취소"),
                        h("button", { key: "save", type: "button", className: "primary", onClick: saveDoc }, loading === "save" ? "저장 중" : "저장")
                      ] : [
                        h("button", { key: "rename", type: "button", onClick: startRenameDoc }, "이름 변경"),
                        h("button", { key: "edit", type: "button", onClick: () => { setDraft(doc.content || ""); setEditMode(true); } }, "수정"),
                        h("button", { key: "delete", type: "button", className: "danger", onClick: deleteDoc }, loading === "delete" ? "삭제 중" : "삭제")
                      ]
                    )
                  )
                ),
                editMode
                  ? h(RichEditor, {
                      value: draft,
                      source: doc.source,
                      onChange: setDraft,
                      minHeight: "calc(100vh - 230px)",
                      maxSizeBytes: meta ? meta.assetMaxSizeBytes : undefined
                    })
                  : h("div", null,
                      h("div", { className: "doc-body" }, h(Markdown, { text: doc.content, source: doc.source })),
                      (() => {
                        const imgs = extractDocImages(doc.source, doc.content || "");
                        if (!imgs.length) return null;
                        return h("div", { className: "doc-images" },
                          h("div", { className: "doc-images-title" }, "첨부 이미지"),
                          h("div", { className: "doc-images-grid" },
                            imgs.map((img) => h("div", { key: img.dbPath, className: "doc-image-item" },
                              h("img", { src: img.url, alt: img.alt, loading: "lazy" }),
                              h("div", { className: "doc-image-footer" },
                                h("span", { title: img.rawPath }, img.rawPath.split("/").pop()),
                                h("button", {
                                  type: "button",
                                  className: "img-delete-btn",
                                  title: "이미지 휴지통으로 이동",
                                  onClick: () => deleteAsset(img.dbPath)
                                }, "×")
                              )
                            ))
                          )
                        );
                      })()
                    )
              ) : h("div", { className: "reader-empty" },
                h("div", { className: "empty" }, loading === "doc" ? "자료를 여는 중입니다." : "왼쪽에서 자료를 선택하거나 오른쪽에서 검색하세요.")
              )
            )
          ),

          h("div", {
            className: "resizer right-resizer " + (draggingSide === "right" ? "dragging" : ""),
            onPointerDown: (event) => startResize("right", event),
            title: "오른쪽 사이드바 폭 조절"
          }),

          h("aside", { className: "right-sidebar" },
            h("div", { className: "tool-head" },
              h("div", { className: "panel-title-row" },
                h("div", { className: "panel-actions" },
                  h("button", {
                    type: "button",
                    className: "icon-button",
                    title: "오른쪽 사이드바 접기",
                    onClick: () => setRightCollapsed(true)
                  }, "›")
                ),
                h("h2", null, "검색 / 질문")
              ),
              h("p", null, "검색 결과에서 자료를 열거나 문서 기반 답변을 확인")
            ),
            h("div", { className: "tool-tabs" },
              h("button", {
                type: "button",
                className: activeTool === "search" ? "active" : "",
                onClick: () => setActiveTool("search")
              }, "검색"),
              h("button", {
                type: "button",
                className: activeTool === "question" ? "active" : "",
                onClick: () => setActiveTool("question")
              }, "질문")
            ),
            h("div", { className: "tool-panel" },
              activeTool === "search" ? [
                h("form", { key: "search-form", className: "tool-form", onSubmit: runSearch },
                  h("div", { className: "search-row" },
                    h("input", {
                      value: searchQuery,
                      onChange: (event) => setSearchQuery(event.target.value),
                      placeholder: "키워드를 입력해주세요"
                    }),
                    h("button", { className: "primary", type: "submit" }, loading === "search" ? "중" : "검색")
                  ),
                  h("select", { value: topK, onChange: (event) => setTopK(Number(event.target.value)) },
                    [3, 5, 8, 10].map((n) => h("option", { key: n, value: n }, "근거 " + n))
                  )
                ),
                search && h("div", { key: "search-answer", className: "answer" }, h(Markdown, { text: search.answer })),
                search && h("div", { key: "search-results" },
                  h("div", { className: "section-title" }, "검색 결과"),
                  search.results.map((item) => h("button", {
                    key: item.source + item.title,
                    className: "result-item",
                    onClick: () => openDoc(item.source)
                  },
                    h("strong", null, item.title),
                    h("p", null, item.source + " / score " + item.score),
                    h("p", null, item.snippet)
                  ))
                )
              ] : [
                h("form", { key: "question-form", className: "tool-form", onSubmit: askChat },
                  h("textarea", {
                    rows: 5,
                    value: chatQuery,
                    onChange: (event) => setChatQuery(event.target.value),
                    placeholder: "문서 기반으로 질문하기"
                  }),
                  h("select", { value: answerProvider, onChange: (event) => setAnswerProvider(event.target.value) },
                    h("option", { value: "local" }, "로컬 LLM (기본)"),
                    h("option", { value: "quick" }, "문서 기반 빠른 답변"),
                    h("option", { value: "claude" }, "Claude API")
                  ),
                  answerProvider === "claude" && h("input", {
                    type: "password",
                    value: claudeApiKey,
                    onChange: (event) => setClaudeApiKey(event.target.value),
                    placeholder: "Anthropic API Key (저장하지 않음)"
                  }),
                  answerProvider === "claude" && h("select", {
                    value: claudeModel,
                    onChange: (event) => setClaudeModel(event.target.value)
                  },
                    h("option", { value: "claude-sonnet-4-5" }, "Claude Sonnet 4.5"),
                    h("option", { value: "claude-opus-4-1-20250805" }, "Claude Opus 4.1"),
                    h("option", { value: "claude-3-5-haiku-20241022" }, "Claude 3.5 Haiku")
                  ),
                  h("div", { className: "toolbar" },
                    h("select", { value: topK, onChange: (event) => setTopK(Number(event.target.value)) },
                      [3, 5, 8, 10].map((n) => h("option", { key: n, value: n }, "근거 " + n))
                    ),
                    h("label", { className: "toggle" },
                      h("input", { type: "checkbox", checked: useLlm, onChange: (event) => setUseLlm(event.target.checked) }),
                      "LLM 답변"
                    )
                  ),
                  h("button", { className: "primary", type: "submit" }, loading === "chat" ? "답변 중" : "질문하기")
                ),
                chatAnswer && h("div", { key: "question-answer", className: "answer" }, h(Markdown, { text: chatAnswer }))
              ]
            )
          ),

          h("nav", { className: "side-rail right-rail", "aria-label": "오른쪽 메뉴" },
            h("button", {
              type: "button",
              className: "rail-button " + (!rightCollapsed ? "active" : ""),
              title: rightCollapsed ? "검색/질문 펼치기" : "검색/질문 접기",
              onClick: () => setRightCollapsed((value) => !value)
            }, "⌕"),
            h("button", {
              type: "button",
              className: "rail-button",
              title: "검색/질문 폭 초기화",
              onClick: () => setRightWidth(360)
            }, "↔"),
            h("div", { className: "rail-spacer" })
          )
        );
      }

      ReactDOM.createRoot(document.getElementById("root")).render(h(App));
