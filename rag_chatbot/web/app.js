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
        const [docFilter, setDocFilter] = React.useState("");
        const [openFolders, setOpenFolders] = React.useState({});
        const [selected, setSelected] = React.useState("");
        const [doc, setDoc] = React.useState(null);
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
          api("/api/meta").then((data) => {
            setMeta(data);
            if (data.claudeDefaultModel) setClaudeModel(data.claudeDefaultModel);
          }).catch((err) => setError(err.message));
          api("/api/docs").then((data) => {
            const list = data.docs || [];
            setDocs(list);
            const firstFolders = {};
            list.slice(0, 1).forEach((item) => { firstFolders[item.customer || "기타"] = true; });
            setOpenFolders(firstFolders);
          }).catch((err) => setError(err.message));
        }, []);

        const groupedDocs = React.useMemo(() => {
          const q = docFilter.trim().toLowerCase();
          const groups = new Map();
          docs.forEach((item) => {
            const haystack = [item.title, item.customer, item.source].join(" ").toLowerCase();
            if (q && !haystack.includes(q)) return;
            const key = item.customer || "기타";
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(item);
          });
          return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0], "ko"));
        }, [docs, docFilter]);

        const openDoc = (source) => {
          setSelected(source);
          setLoading("doc");
          setError("");
          api("/api/doc?source=" + encodeURIComponent(source))
            .then(setDoc)
            .catch((err) => setError(err.message))
            .finally(() => setLoading(""));
        };

        const toggleFolder = (folder) => {
          setOpenFolders((prev) => ({ ...prev, [folder]: !prev[folder] }));
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
              })
            ),
            h("div", { className: "folder-list" },
              groupedDocs.map(([folder, items]) => {
                const isOpen = !!openFolders[folder] || !!docFilter.trim();
                return h("div", { key: folder, className: "folder" },
                  h("button", {
                    className: "folder-toggle " + (isOpen ? "open" : ""),
                    onClick: () => toggleFolder(folder)
                  },
                    h("span", null, isOpen ? "▾" : "▸"),
                    h("strong", null, folder),
                    h("span", null, items.length)
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
              doc ? h("article", { className: "doc-view" },
                h("div", { className: "doc-header" },
                  h("div", { className: "path" }, doc.source),
                  h("h2", null, doc.title)
                ),
                h("div", { className: "doc-body" }, h(Markdown, { text: doc.content, source: doc.source }))
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
          )
        );
      }

      ReactDOM.createRoot(document.getElementById("root")).render(h(App));
