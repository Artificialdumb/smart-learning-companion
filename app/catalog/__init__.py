import re
from datetime import date
from pathlib import Path

from app._analysis import rubric_limits
from app.catalog.locations import STANDARD_CLAUSES, TEXTBOOK_LOCATIONS, matches_verified_pdf
from app.csv_input import index_rows, read_rows, split_ids
from app.rules import curriculum

# Curriculum mapping lives in curriculum.json so a new textbook or standard is a data change.
_CURRICULUM = curriculum()
STANDARD_FILE = _CURRICULUM['standard_file']
STANDARD_PAGES = _CURRICULUM['standard_pages']
TEXTBOOKS = dict(_CURRICULUM['textbooks'])
RELATIONS = tuple(
    (row['from'], row['to'], row['type'], row['reason']) for row in _CURRICULUM['learning_relations']
)


def _rubric(row):
    item_id = row['材料编号']
    points = []
    for line in row['评分点'].splitlines():
        match = re.fullmatch(r'(\S+)\s+(.+?)\s+(\d+)\s*分', line.strip())
        if not match:
            raise ValueError(f'{item_id}: 无法解析评分点 {line!r}')
        point_id, criterion, score = match.groups()
        points.append({'rubric_point_id': point_id, 'criterion': criterion, 'max_score': int(score)})
    return points


def build_catalog(source_dir):
    """Return the JSON-serializable catalog shared by the downstream modules."""
    requirements = index_rows(read_rows(source_dir, '课程要求.csv',
        '主题编号|主题|主题目标|指标编号|观察指标|课标整理编号|课标文件页／正文页|教材正文页'), '指标编号')
    materials = index_rows(read_rows(source_dir, '题目与材料.csv',
        '材料编号|主题编号|材料类型|题型|题干或内容|选项|参考答案|参考解析|满分|评分点|指标编号|来源或资料文件'), '材料编号')
    node_rows = index_rows(read_rows(source_dir, '测验节点.csv',
        '节点编号|模拟测验日期|说明|可用题目编号'), '节点编号')

    topics, indicators, resources, items, nodes = {}, [], {}, {}, []
    resource_types = {'题目': 'item', '学习卡': 'learning_card', '教材': 'textbook'}
    for resource_id, row in materials.items():
        kind = resource_types[row['材料类型']]
        indicator_ids = split_ids(row['指标编号'])
        if len(indicator_ids) != len(set(indicator_ids)):
            raise ValueError(f'{resource_id}: 关联指标重复')
        for indicator_id in indicator_ids:
            if indicator_id not in requirements or requirements[indicator_id]['主题编号'] != row['主题编号']:
                raise ValueError(f'{resource_id}: 指标不存在或主题不匹配：{indicator_id}')
        source = row['来源或资料文件']
        locator = {'file': source} if kind == 'textbook' else {'source': source, 'material_id': resource_id}
        if kind == 'textbook' and not (Path(source_dir) / source).is_file():
            raise ValueError(f'{resource_id}: 缺少教材文件 {source}')
        resources[resource_id] = {
            'resource_id': resource_id, 'resource_type': kind, 'title': row['题干或内容'],
            'indicator_ids': indicator_ids, 'source_locator': locator,
        }
        if kind == 'item':
            if not indicator_ids:
                raise ValueError(f'{resource_id}: 题目缺少观察指标')
            items[resource_id] = {
                'item_id': resource_id, 'topic_id': row['主题编号'], 'indicator_ids': indicator_ids,
                'item_type': row['题型'], 'prompt': row['题干或内容'], 'options': row['选项'].splitlines(),
                'max_score': int(row['满分']), 'rubric_points': _rubric(row),
                'reference_answer': row['参考答案'], 'reference_explanation': row['参考解析'],
            }
            rubric_limits(items[resource_id])

    if not (Path(source_dir) / STANDARD_FILE).is_file():
        raise ValueError(f'缺少课标文件 {STANDARD_FILE}')
    standard_verified = matches_verified_pdf(Path(source_dir) / STANDARD_FILE, 'standard')
    verified_textbooks = {
        resource_id for resource_id in TEXTBOOKS.values() if resource_id in resources
        and matches_verified_pdf(Path(source_dir) / resources[resource_id]['source_locator']['file'], resource_id)
    }
    for indicator_id, row in requirements.items():
        topic_id = row['主题编号']
        topic = {'topic_id': topic_id, 'title': row['主题'], 'goal': row['主题目标']}
        if topics.setdefault(topic_id, topic) != topic:
            raise ValueError(f'{topic_id}: 同一主题的标题或目标不一致')
        file_page, printed_page = (int(page) for page in row['课标文件页／正文页'].split('／'))
        standard_id = row['课标整理编号']
        standard_locator = {'file': STANDARD_FILE, 'pdf_page': file_page, 'printed_page': printed_page}
        standard = resources.setdefault(standard_id, {
            'resource_id': standard_id, 'resource_type': 'curriculum_standard',
            'title': f"{row['主题']}对应课标", 'indicator_ids': [], 'source_locator': standard_locator,
        })
        if standard['source_locator'] != standard_locator:
            raise ValueError(f'{standard_id}: 同一课标编号的定位不一致')
        standard['indicator_ids'].append(indicator_id)
        textbook = resources[TEXTBOOKS[topic_id]]
        textbook['indicator_ids'].append(indicator_id)
        textbook_locator = {'file': textbook['source_locator']['file'], 'chapter': textbook['title'],
                            'printed_pages': row['教材正文页']}
        textbook['source_locator'].update(textbook_locator)
        standard_reference = {'resource_id': standard_id, **standard_locator,
                              'locator': f'正文第 {printed_page} 页（PDF 第 {file_page} 页）'}
        expected_page = tuple(STANDARD_PAGES.get(topic_id, STANDARD_PAGES['default']))
        if standard_verified and (file_page, printed_page) == expected_page and indicator_id in STANDARD_CLAUSES:
            section, *clauses = STANDARD_CLAUSES[indicator_id]
            standard_reference.update(section=section, clauses=clauses)
            standard_reference['locator'] += f'，{section} {"".join(clauses)}'
        textbook_references = []
        if textbook['resource_id'] in verified_textbooks:
            for section, pdf_pages, printed_pages in TEXTBOOK_LOCATIONS.get(indicator_id, ()):
                textbook_references.append({
                    'resource_id': textbook['resource_id'], **textbook_locator,
                    'section': section, 'pdf_page': pdf_pages[0], 'pdf_pages': list(pdf_pages),
                    'printed_page': printed_pages[0], 'printed_page_range': list(printed_pages),
                    'locator': (f'{section}，正文第 {printed_pages[0]}–{printed_pages[1]} 页'
                                f'（PDF 第 {pdf_pages[0]}–{pdf_pages[1]} 页）'),
                })
        if textbook_references:
            textbook.setdefault('indicator_locations', {})[indicator_id] = textbook_references
        indicators.append({'indicator_id': indicator_id, 'topic_id': topic_id,
                           'description': row['观察指标'], 'references': [standard_reference, *(
                               textbook_references or [{
                                   'resource_id': textbook['resource_id'], **textbook_locator,
                                   'locator': f"{textbook['title']}，{row['教材正文页']}",
                               }]
                           )]})

    for node_id, row in node_rows.items():
        item_ids = split_ids(row['可用题目编号'])
        if not item_ids or len(set(item_ids)) != len(item_ids) or set(item_ids) - items.keys():
            raise ValueError(f'{node_id}: 可用题目为空、重复或不存在')
        assessment_date = date.fromisoformat(row['模拟测验日期']).isoformat()
        nodes.append({'node_id': node_id, 'assessment_date': assessment_date,
                      'title': row['说明'].partition('：')[0], 'description': row['说明'],
                      'item_ids': item_ids})

    indicator_index = index_rows(indicators, 'indicator_id')
    return {
        'topics': list(topics.values()), 'indicators': indicators, 'items': list(items.values()),
        'resources': list(resources.values()), 'nodes': nodes,
        'learning_relations': [
            {'from_indicator_id': start, 'to_indicator_id': end, 'relation_type': kind, 'reason': reason,
             'references': [
                 {'indicator_id': indicator_id, **reference}
                 for indicator_id in (start, end) for reference in indicator_index[indicator_id]['references']
             ]}
            for start, end, kind, reason in RELATIONS if start in indicator_index and end in indicator_index
        ],
    }
