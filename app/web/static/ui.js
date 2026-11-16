export const labels = {
  practice_needed: "针对性巩固", strength: "变式练习", observe_more: "补充观察",
  supported: "有作答证据", insufficient: "已测 · 证据不足", not_assessed: "该节点未测",
  item: "题目", learning_card: "学习卡", textbook: "教材", curriculum_standard: "课程标准",
  graded: "已评分", pending: "待评分", unanswered: "未作答",
};

export function el(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value !== undefined) element.setAttribute(name, value);
  }
  element.append(...children.flat().filter(child => child != null && child !== false));
  return element;
}

export function button(label, action, style = "secondary") {
  const control = el("button", {type: "button", class: style}, label);
  control.addEventListener("click", action);
  return control;
}

export function tag(status) {
  return el("span", {class: `tag ${status}`}, labels[status] ?? status);
}

export function metric(value) {
  return value == null ? "—" : new Intl.NumberFormat("zh-CN", {
    style: "percent", maximumFractionDigits: 1,
  }).format(value);
}

export function locator(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") return Object.values(value).filter(Boolean).join("，");
  return "";
}

export function table(headers, rows) {
  return el("div", {class: "table-wrap"},
    el("table", {},
      el("thead", {}, el("tr", {}, headers.map(h => el("th", {scope: "col"}, h)))),
      el("tbody", {}, rows.map(row => el("tr", {}, row.map(v => el("td", {}, v)))))));
}

export function panel(title, action, ...rows) {
  return el("section", {class: "panel"},
    el("div", {class: "panel-head"}, el("h2", {}, title), action), ...rows);
}

export function setOptions(select, rows, value, title) {
  select.replaceChildren(...rows.map(row => el("option", {value: value(row)}, title(row))));
}
