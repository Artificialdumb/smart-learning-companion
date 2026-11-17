import {evidenceButtons} from "./reports.js";
import {button, el, labels} from "./ui.js";

const dimensions = {concept: "概念理解", calculation: "计算执行", reading: "条件理解"};
const outcomes = {pass: "本题通过", gap: "需核查", uncertain: "未确定"};

export function followupPanel(initial, save, reload, openRecord) {
  const container = el("div");
  function render(view) {
    const result = view.result;
    const output = result && el("section", {class: "findings", "aria-label": "追问反馈"},
      el("h3", {}, `最近一次追问 · 版本 ${view.version}`),
      el("p", {class: "meta"}, new Date(result.submitted_at).toLocaleString("zh-CN")),
      el("p", {}, result.conclusion),
      el("ul", {}, result.checks.map(check => el("li", {},
        `${dimensions[check.dimension]}：${outcomes[check.outcome]}`,
        el("details", {}, el("summary", {}, "本题反馈"), el("p", {}, check.prompt),
          el("p", {}, `你的选择：${check.options.find(o => o.option_id === check.selected_option_id)?.text ?? "不确定"}`),
          el("p", {}, check.explanation))))),
      el("p", {class: "meta"}, result.limitation));
    if (!view.questions.length) {
      container.replaceChildren(el("p", {}, view.unavailable_reason), ...(output ? [output] : []));
      return;
    }
    const form = el("form", {}, el("p", {class: "meta"},
      "请学生独立完成这 3 道小题；不确定时如实选择。提交后保存反馈，不改变原测验分数。"));
    const fields = view.questions.map((question, i) => el("fieldset", {},
      el("legend", {}, `${i + 1}. ${question.prompt}`),
      [...question.options, {option_id: "unsure", text: "不确定"}].map(option =>
        el("label", {class: "probe-option"},
          el("input", {type: "radio", name: question.question_id, value: option.option_id, required: ""}),
          el("span", {}, option.text)))));
    const status = el("p", {role: "status", "aria-live": "polite"});
    const submit = el("button", {type: "submit", class: "primary"}, result ? "重新作答并保存" : "提交追问");
    const refresh = button("重新读取（清除本次选择）", async () => {
      refresh.disabled = true;
      try { render(await reload()); }
      catch (error) { status.textContent = error.message; refresh.disabled = false; }
    });
    refresh.hidden = true;
    form.append(...fields, el("div", {class: "actions"}, submit, refresh), status);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const answers = Object.fromEntries(new FormData(form));
      submit.disabled = true;
      fields.forEach(field => { field.disabled = true; });
      status.textContent = "正在保存…";
      try {
        render(await save({expected_version: view.version, probe_version: view.probe_version, answers}));
        const feedback = container.querySelector("[aria-label='追问反馈']");
        feedback.tabIndex = -1;
        feedback.focus();
      } catch (error) {
        status.textContent = error.message;
        status.className = "error";
        refresh.hidden = error.status !== 409;
        submit.disabled = false;
        fields.forEach(field => { field.disabled = false; });
      }
    });
    container.replaceChildren(
      el("details", {}, el("summary", {}, "原始失分证据"), evidenceButtons(view.evidence, openRecord)),
      ...(output ? [output] : []), form);
  }
  render(initial);
  return container;
}

export function pathDetails(path, model, openResource, openRecord) {
  const name = id => model.indicators.get(id)?.description ?? id;
  const actions = {practice: "先补学", check: "先补充观察", continue: "已有作答支持，可继续"};
  return [
    el("p", {}, path.note),
    el("ol", {class: "path-list"}, path.steps.map(step => el("li", {},
      el("h3", {}, name(step.indicator_id)),
      el("p", {class: "meta"},
        step.indicator_id === path.target_indicator_id ? "回到目标指标" : actions[step.action],
        ` · ${labels[step.evidence_status]} · ${step.evidence_node_id}`,
        step.historical ? "（历史证据，建议先复查）" : ""),
      step.action === "check" ? el("p", {}, "缺少足够证据，请先补测或由教师观察，暂不判为薄弱。") : null,
      evidenceButtons(step.evidence, openRecord),
      el("div", {class: "tags"}, [...step.resource_ids, ...step.practice_item_ids].map(id => button(
        `${id} · ${labels[model.resources.get(id)?.resource_type] ?? "材料"}`,
        () => openResource(id), "link-button"))),
      !step.resource_ids.length && !step.practice_item_ids.length
        ? el("p", {class: "meta"}, "该指标暂无适用材料，请由教师安排补充观察。") : null,
    ))),
    path.relations.length ? el("details", {}, el("summary", {}, "前置关系依据"),
      el("ul", {}, path.relations.map(rel => el("li", {},
        `${name(rel.from_indicator_id)} → ${name(rel.to_indicator_id)}：${rel.reason}`)))) : null,
  ];
}
