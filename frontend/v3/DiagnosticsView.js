import { React, h } from "../shared/react.js";

export function DiagnosticsView({ stats, onRefresh }) {
  const nodeCounts = stats.nodeCounts || {};
  const edgeCounts = stats.edgeCounts || {};
  const coverage = Math.round((stats.entityCoverage || 0) * 1000) / 10;
  const excluded = stats.excludedSources || [];

  return h("div", null,
    h("div", { className: "v3-grid", style: { marginBottom: "16px" } },
      stat("문서", stats.docCount, stats.storage === "supabase" ? "Supabase" : "파일 스토리지"),
      stat("청크", stats.chunkCount, "1200자 · 150자 오버랩"),
      stat("그래프 노드", stats.nodeCount, `엣지 ${fmt(stats.edgeCount)}개`),
      stat("엔티티 커버리지", `${coverage}%`, "규칙 기반 · LLM 미사용"),
    ),

    h("div", { className: "v3-panel" },
      h("div", { className: "v3-card" },
        h("h3", null, "허브 엔티티 분포"),
        h("p", { className: "v3-note", style: { marginBottom: "12px" } },
          "전체 청크 대비 연결 비율. 비율이 높을수록 그 엔티티는 문서를 변별하지 못하며, 확장 경로로 쓰면 노이즈만 늘립니다."),
        (stats.hubs || []).map((hub) => h("div", { key: hub.label, style: { marginBottom: "9px" } },
          h("div", {
            style: {
              display: "flex", justifyContent: "space-between",
              fontSize: "12.5px", marginBottom: "3px",
            },
          },
            h("span", null, hub.label,
              h("span", { style: { color: "var(--v3-text-muted)", marginLeft: "6px" } },
                hub.type === "System" ? "시스템" : "이슈유형")),
            h("span", {
              style: {
                fontVariantNumeric: "tabular-nums",
                color: hub.share > 0.4 ? "var(--v3-warn)" : "var(--v3-text-dim)",
                fontWeight: hub.share > 0.4 ? 600 : 400,
              },
            }, `${Math.round(hub.share * 100)}% · ${fmt(hub.degree)}`),
          ),
          h("div", {
            style: {
              height: "5px", borderRadius: "3px",
              background: "var(--v3-border)", overflow: "hidden",
            },
          },
            h("div", {
              style: {
                width: `${Math.min(100, Math.round(hub.share * 100))}%`,
                height: "100%",
                background: hub.share > 0.4 ? "var(--v3-warn)" : "var(--v3-node-system)",
              },
            }),
          ),
        )),
      ),

      h("aside", { className: "v3-side" },
        h("div", { className: "v3-card" },
          h("h3", null, "노드 구성"),
          h("ul", { className: "v3-list" },
            Object.keys(nodeCounts).sort((a, b) => nodeCounts[b] - nodeCounts[a]).map((k) =>
              h("li", { key: k },
                h("span", { className: "k" }, k),
                h("span", { className: "v" }, fmt(nodeCounts[k])))),
          ),
        ),
        h("div", { className: "v3-card" },
          h("h3", null, "엣지 구성"),
          h("ul", { className: "v3-list" },
            Object.keys(edgeCounts).sort((a, b) => edgeCounts[b] - edgeCounts[a]).map((k) =>
              h("li", { key: k },
                h("span", { className: "k" }, k),
                h("span", { className: "v" }, fmt(edgeCounts[k])))),
          ),
        ),
        h("div", { className: "v3-card" },
          h("h3", null, "인덱스에서 제외됨"),
          excluded.length
            ? h("ul", { className: "v3-list" },
                excluded.map((s) => h("li", { key: s },
                  h("span", { className: "k", title: s }, s))))
            : h("p", { className: "v3-note" }, "제외된 문서가 없습니다."),
          h("p", { className: "v3-note", style: { marginTop: "10px" } },
            "저장소 메타 문서는 유지보수 콘텐츠가 아니면서 도메인 어휘를 대량 포함해 렉시컬 상위를 점유합니다."),
          h("button", {
            className: "v3-btn",
            style: { marginTop: "10px", width: "100%" },
            onClick: onRefresh,
          }, "그래프 다시 만들기"),
        ),
      ),
    ),

    h("p", { className: "v3-note", style: { marginTop: "16px" } },
      "이 지표는 그래프 구조만 측정합니다. 검색 품질(Recall@k, NDCG)은 평가셋 구축 후 별도 측정 대상입니다."),
  );
}

function stat(label, value, note) {
  return h("div", { className: "v3-card", key: label },
    h("div", { className: "v3-stat-label" }, label),
    h("div", { className: "v3-stat-value" }, typeof value === "number" ? fmt(value) : value),
    note ? h("div", { className: "v3-stat-note" }, note) : null,
  );
}

function fmt(n) {
  return typeof n === "number" ? n.toLocaleString("ko-KR") : n;
}
