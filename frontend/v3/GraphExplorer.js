import { React, h } from "../shared/react.js";

const { useState, useEffect, useRef, useCallback, useMemo } = React;

const W = 900;
const H = 560;

const NODE_COLOR = {
  Customer: "var(--v3-node-customer)",
  Document: "var(--v3-node-document)",
  Chunk: "var(--v3-node-chunk)",
  Ticket: "var(--v3-node-ticket)",
  Person: "var(--v3-node-person)",
  System: "var(--v3-node-system)",
  IssueType: "var(--v3-node-issue)",
};

const NODE_LABEL = {
  Customer: "고객사",
  Document: "문서",
  Chunk: "청크",
  Ticket: "접수건",
  Person: "담당자",
  System: "시스템",
  IssueType: "이슈유형",
};

function radius(n) {
  if (n.type === "Customer") return 11;
  if (n.type === "Document") return 6.5;
  if (n.type === "Chunk") return 3.5;
  if (n.type === "Ticket") return 4.5;
  if (n.type === "Person") return 8;
  return 5 + Math.sqrt(n.degree || 1) * 0.62;
}

export function GraphExplorer({ stats, onRefresh }) {
  const [picked, setPicked] = useState(() => (stats.customers || []).slice(0, 3).map((c) => c.name));
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [seed, setSeed] = useState(null);
  const [hubPenalty, setHubPenalty] = useState(true);
  const [expansion, setExpansion] = useState(null);
  const [hover, setHover] = useState(null);

  const svgRef = useRef(null);
  const wrapRef = useRef(null);
  const simRef = useRef(null);

  const available = useMemo(
    () => new Set((stats.customers || []).map((c) => c.name)),
    [stats.customers],
  );

  useEffect(() => {
    setPicked((cur) => {
      const kept = cur.filter((name) => available.has(name));
      if (kept.length) return kept.length === cur.length ? cur : kept;
      return (stats.customers || []).slice(0, 3).map((c) => c.name);
    });
  }, [available, stats.customers]);

  useEffect(() => {
    if (!picked.length) {
      setGraph({ nodes: [], edges: [] });
      setSeed(null);
      setExpansion(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    const q = new URLSearchParams({ customers: picked.join(","), maxChunksPerDoc: "4" });
    fetch(`/api/v3/graph?${q}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        if (data.error) throw new Error(data.error);
        setGraph(data);
        setSeed(null);
        setExpansion(null);
      })
      .catch((err) => !cancelled && setError(String(err.message || err)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [picked]);

  useEffect(() => {
    if (!seed) { setExpansion(null); return; }
    let cancelled = false;
    setExpansion(null);
    const q = new URLSearchParams({
      seeds: String(seed),
      hubPenalty: hubPenalty ? "1" : "0",
      intent: "customer_info",
    });
    fetch(`/api/v3/expand?${q}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        if (data.error) throw new Error(data.error);
        setExpansion(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(`확장 계산에 실패했습니다 — ${err.message || err}`);
        setSeed(null);
      });
    return () => { cancelled = true; };
  }, [seed, hubPenalty]);

  const reachedIds = useMemo(() => {
    if (!expansion) return null;
    return new Set(expansion.reached.map((r) => r.id));
  }, [expansion]);

  useEffect(() => {
    if (!graph) return;
    if (!window.d3) {
      setError("그래프 라이브러리(d3)를 불러오지 못했습니다. 네트워크에서 cdnjs.cloudflare.com 접근이 차단되었을 수 있습니다.");
      return;
    }
    const d3 = window.d3;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const nodes = graph.nodes.map((n) => ({ ...n }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = graph.edges
      .filter((e) => byId.has(e.s) && byId.has(e.t))
      .map((e) => ({ source: e.s, target: e.t, type: e.type }));

    const linkSel = svg.append("g")
      .attr("stroke-width", 0.6)
      .selectAll("line").data(links).join("line")
      .style("stroke", "var(--v3-border-strong)")
      .style("stroke-opacity", 0.5);

    const nodeSel = svg.append("g").selectAll("g").data(nodes).join("g")
      .style("cursor", "pointer");

    nodeSel.append("circle")
      .attr("r", radius)
      .style("fill", (d) => NODE_COLOR[d.type] || "var(--v3-node-chunk)")
      .style("stroke", "var(--v3-surface)")
      .style("stroke-width", 1.2);

    nodeSel.filter((d) => d.type === "Customer" || d.type === "System" || d.type === "IssueType")
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => -radius(d) - 5)
      .style("font-size", (d) => (d.type === "Customer" ? "12px" : "11px"))
      .style("fill", "var(--v3-text-dim)")
      .text((d) => d.label);

    let hoverFrame = 0;
    nodeSel
      .on("mousemove", function (ev, d) {
        if (hoverFrame) return;
        hoverFrame = requestAnimationFrame(() => {
          hoverFrame = 0;
          const rect = wrapRef.current.getBoundingClientRect();
          setHover({
            x: ev.clientX - rect.left + 14,
            y: ev.clientY - rect.top - 6,
            node: d,
          });
        });
      })
      .on("mouseleave", () => { setHover(null); })
      .on("click", (ev, d) => {
        if (d.type === "Customer") setSeed((cur) => (cur === d.id ? null : d.id));
      });

    const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id)
        .distance((l) => (l.type === "MENTIONS" || l.type === "HAS_ISSUE" ? 70 : 32))
        .strength(0.3))
      .force("charge", d3.forceManyBody().strength(-150))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide().radius((d) => radius(d) + 7))
      .force("x", d3.forceX(W / 2).strength(0.04))
      .force("y", d3.forceY(H / 2).strength(0.07))
      .on("tick", () => {
        nodes.forEach((n) => {
          const r = radius(n) + 16;
          n.x = Math.max(r, Math.min(W - r, n.x));
          n.y = Math.max(r + 10, Math.min(H - r, n.y));
        });
        linkSel
          .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
        nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });

    nodeSel.call(d3.drag()
      .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    simRef.current = { sim, nodeSel, linkSel };
    const stop = setTimeout(() => sim.stop(), 6000);
    return () => {
      clearTimeout(stop);
      if (hoverFrame) cancelAnimationFrame(hoverFrame);
      sim.stop();
      simRef.current = null;
    };
  }, [graph]);

  useEffect(() => {
    const ctx = simRef.current;
    if (!ctx) return;
    const { nodeSel, linkSel } = ctx;
    if (!reachedIds) {
      nodeSel.style("opacity", 1);
      linkSel.style("stroke", "var(--v3-border-strong)").style("stroke-opacity", 0.5);
      return;
    }
    const inSet = (id) => id === seed || reachedIds.has(id);
    nodeSel.style("opacity", (d) => (inSet(d.id) ? 1 : 0.14));
    linkSel
      .style("stroke", (d) => (inSet(d.source.id) && inSet(d.target.id)
        ? "var(--v3-node-customer)" : "var(--v3-border-strong)"))
      .style("stroke-opacity", (d) => (inSet(d.source.id) && inSet(d.target.id) ? 0.8 : 0.06));
  }, [reachedIds, seed, graph]);

  const toggleCustomer = useCallback((name) => {
    setPicked((cur) => (cur.includes(name)
      ? cur.filter((c) => c !== name)
      : cur.length >= 6 ? cur : [...cur, name]));
  }, []);

  const seedName = seed && graph ? (graph.nodes.find((n) => n.id === seed) || {}).label : null;
  const counts = expansion ? expansion.counts || {} : {};
  const reachedTotal = expansion ? expansion.reached.length : null;

  return h("div", null,
    h("div", { className: "v3-panel" },
      h("div", null,
        h("div", { className: "v3-canvas", ref: wrapRef },
          h("svg", {
            ref: svgRef,
            viewBox: `0 0 ${W} ${H}`,
            role: "img",
            "aria-label": "고객사 문서와 엔티티의 관계 그래프",
          }),
          hover && h("div", {
            className: "v3-tip",
            style: { opacity: 1, left: `${hover.x}px`, top: `${hover.y}px` },
          },
            h("div", { style: { fontWeight: 600 } },
              `${NODE_LABEL[hover.node.type] || hover.node.type} · ${hover.node.label}`),
            hover.node.degree ? h("div", { style: { color: "var(--v3-text-dim)" } },
              `전체 연결 ${hover.node.degree}개`) : null,
            hover.node.preview ? h("div", {
              style: { color: "var(--v3-text-dim)", marginTop: "3px" },
            }, hover.node.preview) : null,
          ),
          (loading || !picked.length) && h("div", {
            style: {
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              background: "var(--v3-surface)", opacity: 0.9,
              color: "var(--v3-text-dim)", fontSize: "13px", textAlign: "center",
              padding: "0 24px",
            },
          }, loading ? "그래프를 그리는 중" : "오른쪽에서 고객사를 하나 이상 선택하세요."),
        ),
        h("div", { className: "v3-legend", style: { marginTop: "10px" } },
          Object.keys(NODE_COLOR).map((t) => h("span", { key: t },
            h("span", { className: "v3-dot", style: { background: NODE_COLOR[t] } }),
            NODE_LABEL[t])),
        ),
        error && h("p", { className: "v3-note warn", style: { marginTop: "10px" } }, error),
      ),

      h("aside", { className: "v3-side" },
        h("div", { className: "v3-card" },
          h("h3", null, "고객사 선택"),
          h("div", { className: "v3-chips" },
            (stats.customers || []).slice(0, 24).map((c) => h("button", {
              key: c.name,
              className: "v3-chip",
              "aria-pressed": picked.includes(c.name),
              onClick: () => toggleCustomer(c.name),
            }, `${c.name} ${c.docCount}`)),
          ),
          h("p", { className: "v3-note", style: { marginTop: "10px" } },
            "최대 6곳까지 동시에 볼 수 있습니다. 고객사 노드를 클릭하면 2홉 확장 경로가 표시됩니다."),
        ),

        h("div", { className: "v3-card" },
          h("h3", null, "확장 설정"),
          h("label", { className: "v3-toggle" },
            h("input", {
              type: "checkbox",
              checked: hubPenalty,
              onChange: (e) => setHubPenalty(e.target.checked),
            }),
            h("span", null, "허브 페널티 적용"),
          ),
          h("p", { className: "v3-note", style: { marginTop: "8px" } },
            "연결 수가 많은 엔티티를 경유한 확장을 로그 역비례로 감쇠합니다. 끄면 확장이 코퍼스 전체로 번지는 것을 볼 수 있습니다."),

          seed
            ? h("div", { style: { marginTop: "12px" } },
                h("ul", { className: "v3-list" },
                  h("li", null, h("span", { className: "k" }, "시드 청크"),
                    h("span", { className: "v" },
                      expansion ? (expansion.walkSeeds || []).length : "—")),
                  h("li", null, h("span", { className: "k" }, "도달 노드"),
                    h("span", { className: "v" }, reachedTotal === null ? "—" : reachedTotal)),
                  h("li", null, h("span", { className: "k" }, "도달 청크"),
                    h("span", { className: "v" }, counts.Chunk || 0)),
                  h("li", null, h("span", { className: "k" }, "번진 고객사"),
                    h("span", { className: `v${expansion && expansion.spread > 0.25 ? " hot" : ""}` },
                      expansion
                        ? `${expansion.reachedCustomers} / ${expansion.totalCustomers}`
                        : "—")),
                ),
                h("p", { className: "v3-note", style: { marginTop: "10px" } },
                  `${seedName || "선택한 고객사"}의 청크를 시드로 2홉 확장한 결과입니다. '번진 고객사'가 전체에 가까워지면 확장이 변별력을 잃었다는 뜻입니다. 수치는 전체 그래프 기준이고 캔버스는 선택한 고객사만 그린 표본이라, 강조 표시가 일부만 보일 수 있습니다.`),
                h("button", {
                  className: "v3-btn",
                  style: { marginTop: "10px", width: "100%" },
                  onClick: () => setSeed(null),
                }, "선택 해제"),
              )
            : h("p", { className: "v3-note", style: { marginTop: "12px" } },
                "그래프에서 파란색 고객사 노드를 클릭하면 그 고객사의 청크를 시드로 확장합니다. 실제 검색에서도 시드는 고객사가 아니라 상위 청크입니다."),
        ),

        h("div", { className: "v3-card" },
          h("h3", null, "허브 엔티티"),
          h("ul", { className: "v3-list" },
            (stats.hubs || []).slice(0, 6).map((hub) => h("li", { key: hub.label },
              h("span", { className: "k" }, hub.label),
              h("span", { className: `v${hub.share > 0.4 ? " hot" : ""}` },
                `${Math.round(hub.share * 100)}%`),
            )),
          ),
          h("p", { className: "v3-note", style: { marginTop: "10px" } },
            "전체 청크 중 해당 엔티티가 연결된 비율입니다. 절반을 넘으면 검색 신호로서 가치가 거의 없습니다."),
          h("button", {
            className: "v3-btn",
            style: { marginTop: "10px", width: "100%" },
            onClick: onRefresh,
          }, "그래프 다시 만들기"),
        ),
      ),
    ),
  );
}
