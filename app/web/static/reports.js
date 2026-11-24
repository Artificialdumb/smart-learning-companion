import {button, el, labels, locator, metric, panel, table, tag} from "./ui.js";

export function evidenceButtons(entries, openRecord) {
  return el("div", {class: "actions"}, entries.map(entry => button(
    [entry.record_id, ...entry.rubric_point_ids].join(" · "),
    () => openRecord(entry.record_id, entry), "link-button evidence",
  )));
}

export function masteryLine(mastery) {
  if (!mastery) return null;
  if (mastery.estimate == null) {
    return el("p", {class: "meta"}, tag(mastery.level), " 截至本节点尚无有效作答。");
  }
  const [low, high] = mastery.interval;
  const count = mastery.evidence_count ?? mastery.record_ids.length;
  const ceiling = mastery.level !== "mastered" && mastery.mastered_reachable === false
    ? el("span", {class: "muted"},
      ` · 截至本节点该指标最多 ${mastery.response_capacity} 条作答，“已掌握”至少需 ${mastery.mastered_min_responses} 条满分作答`)
    : null;
  return el("p", {class: "meta number",
    title: "得分比例指数按每条有效作答的得分比例平滑计算，结合证据条数和90%区间阅读。"}, tag(mastery.level),
    ` 得分比例指数 ${metric(mastery.estimate)}（${Math.round(mastery.interval_level * 100)}% 区间 ${metric(low)}–${metric(high)}）`,
    ` · 依据 ${mastery.node_ids.length} 次测验 ${count} 条有效作答`, ceiling);
}

export function diagnosisPanel(report, model, openRecord, openFollowup, openPath) {
  const indicators = [...report.indicators].sort((a, b) => {
    const priority = row => row.findings.some(f => f.evidence.some(e => e.step_numbers?.length))
      ? 0 : ({supported: 1, insufficient: 2, not_assessed: 3})[row.evidence_status];
    return priority(a) - priority(b);
  });
  return panel("指标与作答证据", null, indicators.map((row, index) =>
    el("article", {class: "stack"},
      el("div", {class: "row"}, el("h3", {}, model.indicators.get(row.indicator_id)?.description ?? row.indicator_id),
        tag(row.evidence_status)),
      row.evidence_status !== "not_assessed" && el("p", {class: "meta number"},
        `有效作答 ${row.valid_count}/${row.eligible_item_count} 题`,
        row.max_score_sum ? ` · 得分 ${row.score_sum}/${row.max_score_sum}（${metric(row.score_rate)}）` : ""),
      masteryLine(row.mastery),
      row.findings.length ? el("details", {open: index === 0 ? "" : undefined},
        el("summary", {}, `诊断发现（${row.findings.length}）`),
        row.findings.map(finding => el("div", {class: "findings"},
          el("p", {}, finding.summary), evidenceButtons(finding.evidence, openRecord)))) : null,
      row.findings.some(f => f.kind === "practice_needed") ? el("div", {class: "actions findings"},
        button("错因追问", () => openFollowup(row.indicator_id)),
        button("查看补学路径", () => openPath(row.indicator_id))) : null,
      (row.pending_count || row.unanswered_count || row.review_count || row.missing_record_count)
        ? el("details", {}, el("summary", {}, "覆盖明细"),
          el("p", {class: "meta"},
            `待评分 ${row.pending_count} · 未作答 ${row.unanswered_count} · 待复核 ${row.review_count} · 无记录 ${row.missing_record_count}`))
        : null,
    ),
  ));
}

function classSummary(summary, model, openRecord) {
  if (!summary) return null;
  const name = id => model.indicators.get(id)?.description ?? id;
  const rate = c => `${c.class_id} ${c.score_sum}/${c.max_score_sum}（${metric(c.score_sum / c.max_score_sum)}）`;
  return el("article", {class: "stack class-summary"},
    el("h3", {}, "本测验群体摘要"),
    summary.largest_gaps.length ? table(["指标", "共同题", "两班得分率", "差值"],
      summary.largest_gaps.map(g => [name(g.indicator_id), String(g.item_count),
        g.classes.map(rate).join("；"), `${(g.rate_gap * 100).toFixed(1)} 个百分点`]))
      : el("p", {class: "meta"}, "本测验没有可比较的指标。"),
    summary.shared_misses.length ? el("div", {class: "findings"},
      el("p", {class: "meta"}, "两班均有 2 人以上失分的评分点（按合计失分比例排序）："),
      summary.shared_misses.map(s => el("div", {},
        el("p", {}, `${s.item_id} “${s.criterion}”（${name(s.indicator_id)}）：`
          + s.classes.map(c => `${c.class_id} ${c.missed_students}/${c.scored_students} 人失分`).join("，")),
        evidenceButtons(s.classes.flatMap(c => c.record_ids).map(record_id => ({
          record_id, rubric_point_ids: [s.rubric_point_id]})), openRecord))))
      : el("p", {class: "meta"}, "本测验没有两班共同的失分评分点。"));
}

export function classesPanel(report, model, openResource, openRecord) {
  return panel("同一测验的两班比较",
    el("span", {class: "tag"}, `共同题共 ${report.comparison_item_ids.length} 道`),
    classSummary(report.summary, model, openRecord),
    report.indicators.map(row =>
      el("article", {class: "stack"},
        el("h3", {}, model.indicators.get(row.indicator_id)?.description ?? row.indicator_id),
        row.item_ids.length
          ? el("details", {}, el("summary", {}, `共同有效题（${row.item_ids.length}）`),
            el("div", {class: "tags"}, row.item_ids.map(id => button(id, () => openResource(id), "link-button"))))
          : null,
        table(["班级", "覆盖人数", "有效作答", "得分 / 满分", "得分率"],
          row.classes.map(c => [c.class_id, `${c.covered_students}/${c.class_size}`,
            String(c.valid_count), `${c.score_sum}/${c.max_score_sum}`, metric(c.score_rate)])),
        row.findings.map(finding => el("div", {class: "findings"},
          el("p", {}, finding.summary),
          evidenceButtons((finding.record_ids ?? []).map(record_id => ({
            record_id, rubric_point_ids: [finding.rubric_point_id],
          })), openRecord))),
      ),
    ));
}

export function catalogPanel(catalog, model, openResource) {
  return panel("课程要求与材料", null,
    catalog.topics.map(topic => el("article", {class: "stack"},
      el("h3", {}, topic.title), el("p", {class: "muted"}, topic.goal),
      catalog.indicators.filter(indicator => indicator.topic_id === topic.topic_id).map(indicator => {
        const materials = catalog.resources.filter(resource =>
          resource.indicator_ids.includes(indicator.indicator_id)
          && resource.resource_type !== "curriculum_standard");
        return el("details", {}, el("summary", {}, indicator.description),
          el("div", {class: "findings"},
            (indicator.references ?? []).map(ref =>
              el("p", {class: "meta"},
                button(ref.resource_id, () => openResource(ref.resource_id), "link-button"),
                "　", locator(ref.locator))),
            el("div", {class: "tags"}, materials.map(resource => button(
              `${resource.resource_id} · ${labels[resource.resource_type] ?? "材料"}`,
              () => openResource(resource.resource_id), "link-button"))),
            (catalog.learning_relations ?? []).filter(rel => rel.from_indicator_id === indicator.indicator_id)
              .map(rel => el("p", {class: "meta"},
                `${rel.relation_type} · ${model.indicators.get(rel.to_indicator_id)?.description ?? rel.to_indicator_id}。 ${rel.reason}`)),
          ));
      }),
    )),
    el("div", {class: "stack"}, el("h3", {}, "资料索引"),
      el("p", {class: "meta"}, "查看课标、学习卡和教材切片的来源定位。"),
      el("div", {class: "tags"}, catalog.resources.filter(resource => resource.resource_type !== "item")
        .map(resource => button(resource.title, () => openResource(resource.resource_id), "link-button")))),
  );
}

export function recordDetails(row, evidence) {
  const points = new Set(evidence?.rubric_point_ids ?? []);
  const steps = new Set(evidence?.step_numbers ?? []);
  const recordedSteps = Array.isArray(row.steps) ? row.steps : [];
  const caption = `修订 ${row.revision} · ${labels[row.scoring_status] ?? row.scoring_status}`;
  return [
    el("p", {class: "meta"}, caption, row.score == null ? "" : ` · 得分 ${row.score}/${row.max_score}`),
    el("p", {}, row.prompt),
    el("h3", {}, "实际作答"),
    el("pre", {}, row.final_answer ?? "暂无最终作答"),
    el("h3", {}, "解题步骤"),
    recordedSteps.length ? el("ol", {}, recordedSteps.map((step, i) =>
      el("li", {class: steps.has(i + 1) ? "warning" : undefined},
        steps.has(i + 1) ? "证据步骤 · " : "", step))) : el("p", {class: "muted"}, "该记录没有步骤文本。"),
    el("h3", {}, "评分点"),
    table(["编号", "评分标准", "得分 / 满分"], row.rubric_points.map(point => [
      points.has(point.rubric_point_id) ? el("strong", {}, `${point.rubric_point_id}（引用）`) : point.rubric_point_id,
      point.criterion, `${point.awarded ?? "—"}/${point.max_score}`,
    ])),
  ];
}

export function resourceDetails(row, model) {
  const source = locator(row.source_locator);
  const locations = Object.entries(row.indicator_locations ?? {}).flatMap(([indicatorId, refs]) =>
    refs.map(ref => el("li", {}, model.indicators.get(indicatorId)?.description ?? indicatorId,
      " · ", locator(ref.locator))));
  return [
    el("p", {class: "meta"}, labels[row.resource_type] ?? "材料", source ? ` · ${source}` : ""),
    el("pre", {}, row.prompt ?? row.content ?? row.title),
    row.options?.length ? el("ul", {}, row.options.map(option => el("li", {}, option))) : null,
    locations.length ? el("div", {}, el("h3", {}, "按指标定位"), el("ul", {}, locations)) : null,
  ];
}
