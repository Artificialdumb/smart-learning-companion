import {learningPlan} from "./plan.js";
import {followupPanel, pathDetails} from "./followup.js";
import {catalogPanel, classesPanel, diagnosisPanel, evidenceButtons, recordDetails, resourceDetails} from "./reports.js";
import {button, el, setOptions} from "./ui.js";

const dom = Object.fromEntries([
  "page-title", "page-note", "student-filter", "node-filter", "student", "node",
  "status", "content", "detail", "detail-title", "detail-body",
].map(id => [id, document.getElementById(id)]));
const pages = {
  student: ["个人诊断", "沿作答证据定位问题，查看每项学习活动的依据。"],
  classes: ["班级对比", "以两班都有有效作答的题目为范围，查看覆盖和得分。"],
  catalog: ["课程材料", "按课程指标查找题目、学习卡、课标和教材定位。"],
};

let context;
let catalog;
let model;
let renderStamp = 0;
let detailStamp = 0;
const drafts = new Map();

async function api(path, {node, init} = {}) {
  const params = new URLSearchParams();
  if (path !== "/context") params.set("run_id", context.run_id);
  if (node) params.set("node_id", node);
  const response = await fetch(`/api${path}${params.size ? `?${params}` : ""}`, {cache: "no-store", ...init});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.error?.message ?? `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function message(text, error = false) {
  dom.status.textContent = text;
  dom.status.classList.toggle("error", error);
}

async function detail(title, load) {
  const stamp = ++detailStamp;
  dom["detail-title"].textContent = title;
  dom["detail-body"].replaceChildren(el("p", {role: "status"}, "正在读取…"));
  if (!dom.detail.open) dom.detail.showModal();
  try {
    const content = await load();
    if (stamp === detailStamp && dom.detail.open) dom["detail-body"].replaceChildren(...content.filter(Boolean));
  } catch (error) {
    if (stamp === detailStamp && dom.detail.open) {
      dom["detail-body"].replaceChildren(el("p", {class: "error", role: "alert"}, error.message));
    }
  }
}

function resource(id) {
  detail(`材料 ${id}`, async () => resourceDetails(await api(`/resources/${encodeURIComponent(id)}`), model));
}

function record(id, evidence) {
  detail(`作答证据 ${id}`, async () => recordDetails(await api(`/records/${encodeURIComponent(id)}`), evidence));
}

function page() {
  const name = window.location.hash.slice(1);
  return Object.hasOwn(pages, name) ? name : "student";
}

function storeSelection() {
  const url = new URL(window.location.href);
  url.searchParams.set("student", dom.student.value);
  url.searchParams.set("node", dom.node.value);
  history.replaceState(null, "", url);
}

async function render() {
  if (!context || !catalog) return;
  const stamp = ++renderStamp;
  const view = page();
  const student = dom.student.value;
  const node = dom.node.value;
  const path = `/students/${encodeURIComponent(student)}`;
  dom["page-title"].textContent = pages[view][0];
  dom["page-note"].textContent = pages[view][1];
  dom["student-filter"].hidden = view !== "student";
  dom["node-filter"].hidden = view === "catalog";
  for (const link of document.querySelectorAll("[data-view]")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  dom.content.replaceChildren();
  dom.content.setAttribute("aria-busy", "true");
  message("正在读取…");
  try {
    let results;
    if (view === "catalog") {
      results = catalogPanel(catalog, model, resource);
    } else if (view === "classes") {
      results = classesPanel(await api("/classes/compare", {node}), model, resource, record);
    } else {
      const latest = () => api(`${path}/recommendations`, {node});
      const [report, plan] = await Promise.all([api(`${path}/diagnosis`, {node}), latest()]);
      const findings = new Map(report.indicators.flatMap(row =>
        row.findings.map(finding => [finding.finding_id, finding])));
      const actions = {
        latest, resource,
        finding(id) {
          const finding = findings.get(id);
          detail("诊断依据", async () => [el("p", {}, finding.summary), evidenceButtons(finding.evidence, record)]);
        },
        save: (id, body) => api(`/plans/${encodeURIComponent(id)}/teacher-adjustment`, {
          init: {
            method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
          },
        }),
      };
      const planPanel = learningPlan(plan, model, drafts, actions);
      const openFollowup = indicator => {
        const endpoint = `${path}/followups/${encodeURIComponent(indicator)}`;
        const reload = () => api(endpoint, {node});
        detail(`错因追问 · ${model.indicators.get(indicator)?.description ?? indicator}`, async () => [
          followupPanel(await reload(), body => api(endpoint, {node, init: {
            method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
          }}), reload, record),
        ]);
      };
      const openPath = indicator => detail("前置知识补学路径", async () => {
        const data = await api(`${path}/learning-paths`, {node});
        const selected = data.paths.find(p => p.target_indicator_id === indicator);
        return selected ? pathDetails(selected, model, resource, record)
          : [el("p", {}, data.empty_reason ?? "当前指标没有可用补学路径。")];
      });
      const planTitle = planPanel.querySelector("h2");
      planTitle.tabIndex = -1;
      results = el("div", {class: "workspace"},
        button("跳到学习计划", () => planTitle.focus(), "secondary mobile-jump"),
        diagnosisPanel(report, model, record, openFollowup, openPath), planPanel);
    }
    if (stamp === renderStamp) {
      dom.content.replaceChildren(results);
      message("");
    }
  } catch (error) {
    if (stamp === renderStamp) message(error.message, true);
  } finally {
    if (stamp === renderStamp) dom.content.removeAttribute("aria-busy");
  }
}

async function initialize() {
  message("正在读取当前批次…");
  try {
    context = await api("/context");
    catalog = await api("/catalog");
    model = {
      indicators: new Map(context.indicators.map(row => [row.indicator_id, row])),
      nodes: new Map(context.nodes.map(row => [row.node_id, row])),
      resources: new Map(catalog.resources.map(row => [row.resource_id, row])),
    };
    setOptions(dom.student, context.students, row => row.student_id, row => `${row.student_id} · ${row.class_id}`);
    setOptions(dom.node, context.nodes, row => row.node_id,
      row => `${row.node_id} · ${row.assessment_date ?? row.title}`);
    const params = new URLSearchParams(window.location.search);
    for (const select of [dom.student, dom.node]) {
      const value = params.get(select.id);
      if ([...select.options].some(option => option.value === value)) select.value = value;
      select.addEventListener("change", () => {
        storeSelection();
        render();
      });
    }
    window.addEventListener("hashchange", render);
    render();
  } catch (error) {
    message(error.message, true);
  }
}

initialize();
