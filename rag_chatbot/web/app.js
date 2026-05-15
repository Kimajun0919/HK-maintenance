const h = React.createElement;

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
        if (/^(https?:)?\/\//i.test(url) || url.startsWith("data:")) return url;
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

      function App() {
        const [meta, setMeta] = React.useState(null);
        const [docs, setDocs] = React.useState([]);
        const [folders, setFolders] = React.useState([]);
        const [docFilter, setDocFilter] = React.useState("");
        const [docSort, setDocSort] = React.useState(() => localStorage.getItem("hk.docSort") || "folder");
        const [openFolders, setOpenFolders] = React.useState({});
        const [selected, setSelected] = React.useState("");
        const [doc, setDoc] = React.useState(null);
        const [editMode, setEditMode] = React.useState(false);
        const [draft, setDraft] = React.useState("");
        const [showCreate, setShowCreate] = React.useState(false);
        const [showFolderCreate, setShowFolderCreate] = React.useState(false);
        const [newFolderName, setNewFolderName] = React.useState("");
        const [renamingFolder, setRenamingFolder] = React.useState("");
        const [renameFolderName, setRenameFolderName] = React.useState("");
        const [showRenameDoc, setShowRenameDoc] = React.useState(false);
        const [renameDocFolder, setRenameDocFolder] = React.useState("");
        const [renameDocTitle, setRenameDocTitle] = React.useState("");
        const [newCustomer, setNewCustomer] = React.useState("");
        const [newTitle, setNewTitle] = React.useState("");
        const [newContent, setNewContent] = React.useState("# 새 문서\n\n## 본문\n\n");
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
        const [draggingSide, setDraggingSide] = React.useState("");
        const [loading, setLoading] = React.useState("");
        const [error, setError] = React.useState("");

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
          const entries = Array.from(groups.entries()).filter(([folder, group]) => {
            if (!q) return true;
            return folder.toLowerCase().includes(q) || group.items.length > 0;
          });
          entries.forEach(([, group]) => {
            group.items.sort((a, b) => {
              if (docSort === "title-desc") return compareText(b.title, a.title);
              if (docSort === "path-asc") return compareText(a.source, b.source);
              if (docSort === "path-desc") return compareText(b.source, a.source);
              return compareText(a.title, b.title);
            });
          });
          entries.sort((a, b) => {
            if (docSort === "folder-desc") return compareText(b[0], a[0]);
            if (docSort === "custom") return (a[1].folder.sortOrder ?? 9999) - (b[1].folder.sortOrder ?? 9999) || compareText(a[0], b[0]);
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
          setNewContent("# 새 문서\n\n## 본문\n\n");
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

        const deleteDoc = () => {
          if (!doc) return;
          if (!confirm("이 문서를 삭제할까요? 삭제 후에는 현재 배포 파일 기준으로 복구해야 합니다.")) return;
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

        const appStyle = {
          "--left-width": leftCollapsed ? "0px" : leftWidth + "px",
          "--right-width": rightCollapsed ? "0px" : rightWidth + "px",
          "--left-resizer-width": leftCollapsed ? "0px" : "6px",
          "--right-resizer-width": rightCollapsed ? "0px" : "6px",
        };

        return h("div", {
          className: "app " + (leftCollapsed ? "left-collapsed " : "") + (rightCollapsed ? "right-collapsed" : ""),
          style: appStyle
        },
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
            h("div", { className: "brand" },
              h("div", { className: "panel-title-row" },
                h("h1", null, "HK Maintenance Portal"),
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
              h("span", null, "청크 ", h("b", null, meta ? meta.chunkCount : "-"))
            ),
            h("div", { className: "list-filter" },
              h("input", {
                value: docFilter,
                onChange: (event) => setDocFilter(event.target.value),
                placeholder: "자료 목록 필터"
              }),
              h("select", {
                value: docSort,
                onChange: (event) => setDocSort(event.target.value),
                style: { marginTop: "8px" }
              },
                h("option", { value: "folder" }, "폴더명 오름차순"),
                h("option", { value: "folder-desc" }, "폴더명 내림차순"),
                h("option", { value: "title-asc" }, "파일명 오름차순"),
                h("option", { value: "title-desc" }, "파일명 내림차순"),
                h("option", { value: "path-asc" }, "경로 오름차순"),
                h("option", { value: "path-desc" }, "경로 내림차순"),
                h("option", { value: "custom" }, "폴더 사용자 순서")
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
              ),
              h("button", {
                type: "button",
                className: "primary",
                onClick: startCreate,
                style: { marginTop: "8px", width: "100%", minHeight: "34px" }
              }, "새 문서"),
              h("button", {
                type: "button",
                onClick: () => setShowFolderCreate((value) => !value),
                style: { marginTop: "8px", width: "100%", minHeight: "34px" }
              }, "새 폴더")
            ),
            h("div", { className: "folder-list" },
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
                    : h("div", { className: "folder-row" },
                        h("button", {
                          className: "folder-toggle " + (isOpen ? "open" : ""),
                          onClick: () => toggleFolder(folder)
                        },
                          h("span", null, isOpen ? "▾" : "▸"),
                          h("strong", null, folder),
                          h("span", null, items.length)
                        ),
                        h("button", { type: "button", className: "mini-button", title: "폴더명 수정", onClick: () => startRenameFolder(folder) }, "수정"),
                        h("button", { type: "button", className: "mini-button danger-text", title: "빈 폴더 삭제", onClick: () => deleteFolder(folder) }, "삭제")
                      ),
                  isOpen && h("div", { className: "doc-group" },
                    items.map((item) => h("button", {
                      key: item.source,
                      className: "doc-item " + (selected === item.source ? "selected" : ""),
                      onClick: () => openDoc(item.source)
                    }, h("strong", null, item.title), h("span", null, item.source)))
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
                    h("input", {
                      value: newCustomer,
                      onChange: (event) => setNewCustomer(event.target.value),
                      placeholder: "폴더/고객명"
                    }),
                    h("input", {
                      value: newTitle,
                      onChange: (event) => setNewTitle(event.target.value),
                      placeholder: "문서 제목"
                    })
                  ),
                  h("textarea", {
                    rows: 10,
                    value: newContent,
                    onChange: (event) => setNewContent(event.target.value)
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
                    h("input", {
                      value: renameDocFolder,
                      onChange: (event) => setRenameDocFolder(event.target.value),
                      placeholder: "폴더명"
                    }),
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
                  ? h("textarea", {
                      className: "doc-editor",
                      value: draft,
                      onChange: (event) => setDraft(event.target.value)
                    })
                  : h("div", { className: "doc-body" }, h(Markdown, { text: doc.content, source: doc.source }))
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
                h("h2", null, "검색 / 질문"),
                h("div", { className: "panel-actions" },
                  h("button", {
                    type: "button",
                    className: "icon-button",
                    title: "오른쪽 사이드바 접기",
                    onClick: () => setRightCollapsed(true)
                  }, "›")
                )
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
                      placeholder: "예: 대한항공 방문자 수 확인"
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
