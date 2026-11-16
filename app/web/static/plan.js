import {button, el, labels, panel, setOptions, tag} from "./ui.js";

function editCopy(activities) {
  return activities.map(({recommendation_id, resource_id, sequence, hints, recheck_condition}) =>
    ({recommendation_id, resource_id, sequence, hints: [...hints], recheck_condition}));
}

function activityList(activities, model, openResource, openFinding, title = "") {
  return el("ol", {class: "activity-list", "aria-label": title || "学习活动顺序"},
    activities.map(activity => el("li", {class: "stack"},
      el("div", {class: "row"},
        el("h3", {}, model.indicators.get(activity.indicator_id)?.description ?? activity.indicator_id),
        tag(activity.kind)),
      el("p", {class: "muted"}, activity.reason),
      el("div", {class: "actions"},
        button(`学习材料 ${activity.resource_id}`, () => openResource(activity.resource_id), "link-button"),
        button("查看诊断依据", () => openFinding(activity.finding_ids[0]), "link-button evidence")),
      el("details", {}, el("summary", {}, "分步提示与复查条件"),
        el("ol", {}, activity.hints.map(hint => el("li", {}, hint))),
        el("p", {}, el("strong", {}, "复查条件"), "　", activity.recheck_condition)),
    )));
}

function eligible(model, node, indicator) {
  const itemIds = new Set(model.nodes.get(node).item_ids);
  return [...model.resources.values()].filter(resource =>
    resource.indicator_ids.includes(indicator)
    && (["learning_card", "textbook"].includes(resource.resource_type)
      || (resource.resource_type === "item" && itemIds.has(resource.resource_id))));
}

export function learningPlan(plan, model, drafts, actions) {
  const list = () => activityList(plan.effective_activities, model, actions.resource, actions.finding);
  if (!plan.effective_activities.length) {
    return panel("学习计划", null, el("p", {class: "stack muted"}, plan.empty_reason));
  }
  const key = plan.plan_id;
  const container = panel("学习计划");
  const header = container.firstElementChild;
  const view = el("div");
  container.append(view);
  const buttonEdit = button("教师调整", () => {
    drafts.set(key, {
      version: plan.adjustment_version, rows: editCopy(plan.effective_activities),
    });
    render();
    view.querySelector("select")?.focus();
  });
  const version = el("small", {class: "meta"});
  header.append(el("div", {class: "actions"}, version, buttonEdit));

  function render(focusId) {
    const draft = drafts.get(key);
    version.textContent = plan.adjustment_version ? `已保存 · 版本 ${plan.adjustment_version}` : "原始计划";
    buttonEdit.hidden = Boolean(draft);
    if (!draft) {
      view.replaceChildren(list());
      if (plan.adjustment_version) {
        view.append(el("details", {class: "stack"}, el("summary", {}, "查看原始建议"),
          activityList(plan.original_activities, model, actions.resource, actions.finding, "原始活动顺序")));
      }
      return;
    }

    const originals = new Map(plan.original_activities.map(row => [row.recommendation_id, row]));
    const status = el("p", {role: "status", class: "meta"}, draft.conflict ?? "");
    const form = el("form", {class: "stack"});
    const save = el("button", {type: "submit", class: "primary"}, "保存调整");
    const cancel = button("取消调整", () => {
      drafts.delete(key);
      render();
      buttonEdit.focus();
    });
    const refresh = button("读取最新计划", async () => {
      refresh.disabled = true;
      try {
        plan = await actions.latest();
        draft.version = plan.adjustment_version;
        delete draft.conflict;
        draft.showLatest = true;
        render();
        view.querySelector("select")?.focus();
        view.querySelector("[role=status]").textContent =
          `已读取版本 ${draft.version}。你的编辑仍在表单内，请核对后保存。`;
      } catch (error) {
        status.textContent = error.message;
      } finally {
        refresh.disabled = false;
      }
    });
    refresh.hidden = !draft.conflict;
    save.disabled = Boolean(draft.conflict);

    for (const [position, row] of draft.rows.entries()) {
      const original = originals.get(row.recommendation_id);
      const title = model.indicators.get(original.indicator_id)?.description ?? original.indicator_id;
      const material = el("select", {required: "", "data-edit": row.recommendation_id});
      const resources = eligible(model, plan.node_id, original.indicator_id);
      setOptions(material, resources, resource => resource.resource_id,
        resource => `${resource.resource_id} · ${resource.title}`);
      material.value = row.resource_id;
      material.addEventListener("change", () => { row.resource_id = material.value; });
      const hints = el("textarea", {rows: 3, required: "", maxlength: 1205}, row.hints.join("\n"));
      hints.addEventListener("input", () => { row.hints = hints.value.split("\n"); });
      const recheck = el("textarea", {rows: 2, required: "", maxlength: 300}, row.recheck_condition);
      recheck.addEventListener("input", () => { row.recheck_condition = recheck.value; });
      const move = offset => () => {
        const target = position + offset;
        [draft.rows[position], draft.rows[target]] = [draft.rows[target], draft.rows[position]];
        render(row.recommendation_id);
      };
      const up = button("上移", move(-1));
      const down = button("下移", move(1));
      up.disabled = position === 0;
      down.disabled = position === draft.rows.length - 1;
      form.append(el("fieldset", {}, el("legend", {}, `${position + 1}. ${title}`),
        el("p", {class: "meta"}, labels[original.kind]),
        el("label", {class: "edit-field"}, "学习材料", material),
        el("label", {class: "edit-field"}, "提示（每行一条）", hints),
        el("label", {class: "edit-field"}, "复查条件", recheck),
        el("div", {class: "actions"}, up, down)));
    }
    form.append(el("div", {class: "actions"}, save, cancel, refresh), status);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (draft.conflict) return;
      const fields = [...form.querySelectorAll("fieldset, button")];
      const disabled = fields.map(field => field.disabled);
      fields.forEach(field => { field.disabled = true; });
      status.textContent = "正在保存…";
      try {
        plan = await actions.save(plan.plan_id, {
          expected_version: draft.version,
          activities: draft.rows.map((row, index) => ({
            ...row, sequence: index + 1, hints: row.hints.map(text => text.trim()).filter(Boolean),
          })),
        });
        drafts.delete(key);
        render();
        if (view.isConnected) {
          view.prepend(el("p", {class: "stack meta", role: "status"}, "调整已保存。"));
          buttonEdit.focus();
        }
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
        if (error.status === 409) {
          draft.conflict = error.message;
          render();
          view.querySelector("button:not([hidden])")?.focus();
        }
      } finally {
        fields.forEach((field, index) => { field.disabled = disabled[index]; });
      }
    });
    form.append(el("details", {open: draft.showLatest ? "" : undefined},
      el("summary", {}, "查看当前已保存的活动"), list()));
    view.replaceChildren(form);
    if (focusId) {
      [...form.querySelectorAll("[data-edit]")].find(element => element.dataset.edit === focusId)?.focus();
    }
  }

  render();
  return container;
}
