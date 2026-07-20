import { React, h } from "../shared/react.js";
import { GraphExplorer } from "./GraphExplorer.js";
import { DiagnosticsView } from "./DiagnosticsView.js";

const { useState, useEffect, useCallback } = React;

const VIEWS = [
  { id: "graph", label: "그래프 탐색", ready: true },
  { id: "diagnostics", label: "진단 지표", ready: true },
  { id: "search", label: "하이브리드 검색", ready: false },
  { id: "admin", label: "사전 · 권한", ready: false },
];

export function V3App() {
  const [view, setView] = useState(readHash());
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (refresh) => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/v3/stats${refresh ? "?refresh=1" : ""}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setStats(data);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(false); }, [load]);

  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (id) => { window.location.hash = id; setView(id); };

  return h("div", { className: "v3-shell" },
    h("div", { className: "v3-head" },
      h("h1", null, "HK Maintenance"),
      h("span", { className: "v3-badge" }, "v3 PREVIEW"),
    ),
    h("p", { className: "v3-sub" },
      "온프레미스 Private Graph RAG 전환 미리보기. 그래프는 운영 코퍼스에서 즉석 생성되며 별도 테이블을 만들지 않습니다. ",
      h("a", { href: "/" }, "v1으로 돌아가기"),
    ),

    h("nav", { className: "v3-tabs", role: "tablist" },
      VIEWS.map((v) => h("button", {
        key: v.id,
        className: "v3-tab",
        role: "tab",
        "aria-selected": view === v.id,
        disabled: !v.ready,
        title: v.ready ? undefined : "준비 중",
        onClick: () => v.ready && go(v.id),
      }, v.ready ? v.label : `${v.label} · 준비 중`)),
    ),

    error && h("p", { className: "v3-note warn" }, `그래프를 불러오지 못했습니다 — ${error}`),
    loading && !stats && h("p", { className: "v3-empty" }, "코퍼스에서 그래프를 만드는 중입니다."),

    stats && view === "graph" && h(GraphExplorer, { stats, onRefresh: () => load(true) }),
    stats && view === "diagnostics" && h(DiagnosticsView, { stats, onRefresh: () => load(true) }),
  );
}

function readHash() {
  const raw = (window.location.hash || "").replace("#", "").trim();
  return VIEWS.some((v) => v.id === raw && v.ready) ? raw : "graph";
}
