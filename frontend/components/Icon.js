import { h } from "../shared/react.js";

export const Icon = ({ name }) => {
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
  if (name === "grid-view") {
    return h("svg", common,
      h("rect", { x: 3, y: 3, width: 7, height: 7 }),
      h("rect", { x: 14, y: 3, width: 7, height: 7 }),
      h("rect", { x: 3, y: 14, width: 7, height: 7 }),
      h("rect", { x: 14, y: 14, width: 7, height: 7 })
    );
  }
  if (name === "list-view") {
    return h("svg", common,
      h("line", { x1: 8, y1: 6, x2: 21, y2: 6 }),
      h("line", { x1: 8, y1: 12, x2: 21, y2: 12 }),
      h("line", { x1: 8, y1: 18, x2: 21, y2: 18 }),
      h("line", { x1: 3, y1: 6, x2: 3.01, y2: 6 }),
      h("line", { x1: 3, y1: 12, x2: 3.01, y2: 12 }),
      h("line", { x1: 3, y1: 18, x2: 3.01, y2: 18 })
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
  if (name === "upload") {
    return h("svg", common,
      h("path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }),
      h("polyline", { points: "17 8 12 3 7 8" }),
      h("line", { x1: 12, y1: 3, x2: 12, y2: 15 })
    );
  }
  return null;
};
