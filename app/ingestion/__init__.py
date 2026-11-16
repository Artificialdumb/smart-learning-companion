import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from app.csv_input import DATA_PATH, index_rows, read_rows, split_ids
from app.ingestion.reviews import read_reviews


SCORING_STATUSES = {'已评分': 'graded', '待评分': 'pending', '未作答': 'unanswered'}


@dataclass
class IngestResult:
    students: list
    raw_responses: list
    latest_responses: list
    usable_responses: list
    quality_report: dict


def _integer(value):
    try:
        return int(value)
    except ValueError:
        return None


def _validate_response(row, revision, students, items, nodes, issue):
    student_id, item_id, node_id = (row[key] for key in ('学生编号', '材料编号', '节点编号'))
    item = items.get(item_id)
    node = nodes.get(node_id)
    event = row['作答事件编号']
    if student_id not in students:
        issue('unknown_student', {'student_id': student_id})
    if event != f'{student_id}-{node_id}-{item_id}':
        issue('event_key_mismatch', {'record_key': [student_id, node_id, item_id]})
    if item is None:
        issue('unknown_item', {'item_id': item_id})
    elif row['主题编号'] != item['topic_id']:
        issue('topic_mismatch', {'record_topic': row['主题编号'], 'item_topic': item['topic_id']})
    if node is None:
        issue('unknown_node', {'node_id': node_id})
    elif item_id not in node['item_ids']:
        issue('item_outside_node', {'node_id': node_id, 'item_id': item_id})

    timestamp = row['模拟提交时间']
    try:
        submitted = datetime.fromisoformat(timestamp)
        if submitted.utcoffset() is None:
            raise ValueError('missing offset')
    except ValueError:
        issue('invalid_submitted_at', {'submitted_at': timestamp}, severity='warning')
    else:
        if node and submitted.date().isoformat() != node['assessment_date']:
            issue('submitted_date_differs', {'submitted_at': timestamp,
                  'assessment_date': node['assessment_date']}, severity='warning')

    score, maximum = (_integer(row[key]) for key in ('得分', '满分'))
    status = SCORING_STATUSES.get(row['评分状态'])
    if status is None:
        issue('unknown_scoring_status', {'raw_status': row['评分状态']})
    if maximum is None or maximum <= 0 or (item and maximum != item['max_score']):
        issue('invalid_max_score', {'raw_max_score': row['满分'], 'item_max_score': item and item['max_score']})

    rubric_scores = {}
    for part in split_ids(row['评分点得分']):
        point, _, value = part.partition('=')
        point, value = point.strip(), _integer(value)
        if not point or value is None or point in rubric_scores:
            issue('invalid_rubric_entries', {'raw_rubric_scores': row['评分点得分']})
            break
        rubric_scores[point] = value

    if status == 'graded':
        if score is None or maximum is None or not 0 <= score <= maximum:
            issue('score_out_of_range', {'raw_score': row['得分'], 'raw_max_score': row['满分']})
        if item:
            limits = {point['rubric_point_id']: point['max_score'] for point in item['rubric_points']}
            if limits.keys() != rubric_scores.keys() or any(
                not 0 <= value <= limits[point] for point, value in rubric_scores.items() if point in limits
            ):
                issue('rubric_points_mismatch', {'raw_rubric_scores': row['评分点得分']})
        if score is not None and sum(rubric_scores.values()) != score:
            issue('rubric_total_mismatch', {'score': score, 'rubric_total': sum(rubric_scores.values())})
    elif row['得分'] or row['评分点得分']:
        issue('unexpected_score', {'raw_score': row['得分'], 'raw_rubric_scores': row['评分点得分']})

    return {
        'event_id': event, 'record_id': row['记录编号'], 'revision': revision,
        'student_id': student_id, 'class_id': students.get(student_id, {}).get('class_id'),
        'node_id': node_id, 'item_id': item_id, 'topic_id': row['主题编号'],
        'scoring_status': status, 'raw_scoring_status': row['评分状态'],
        'score': score, 'max_score': maximum, 'submitted_at': timestamp,
        'final_answer': row['学生最终作答'] or None,
        'steps': [re.sub(r'^\d+[.．]\s*', '', step) for step in row['解答过程'].splitlines() if step.strip()],
        'rubric_scores': rubric_scores,
    }


def ingest(source_dir, catalog, *, reviews_path=None):
    """Preserve the original rows and derive the latest and scoreable views."""
    students = {}
    for student_id, row in index_rows(read_rows(source_dir, '模拟学生.csv',
        '学生编号|模拟班级编号|年级'), '学生编号').items():
        grade = _integer(row['年级'])
        if not row['模拟班级编号'] or grade is None or grade <= 0:
            raise ValueError(f'{student_id}: 名册缺少有效班级或年级')
        students[student_id] = {'student_id': student_id, 'class_id': row['模拟班级编号'], 'grade': grade}

    source = (Path(source_dir) / DATA_PATH / '作答记录.csv').read_bytes()
    response_sha256 = sha256(source).hexdigest()
    decisions, review_input = read_reviews(reviews_path, response_sha256)
    raw = read_rows(source_dir, '作答记录.csv', '记录编号|学生编号|材料编号|主题编号|节点编号|作答事件编号|'
        '修订版本|模拟提交时间|评分状态|得分|满分|学生最终作答|解答过程|评分点得分', content=source)
    items = index_rows(catalog['items'], 'item_id')
    nodes = index_rows(catalog['nodes'], 'node_id')
    issues = []
    records = {}
    events = defaultdict(list)
    for row in raw:
        record_id, event_id = row['记录编号'], row['作答事件编号']
        revision = _integer(row['修订版本'])
        if not record_id or not event_id or revision is None or revision < 1:
            raise ValueError(f'{record_id!r}: 缺少可用于追溯的记录编号、事件编号或正整数修订版本')
        if record_id in records:
            if records[record_id] != row:
                raise ValueError(f'{record_id}: 同一记录编号出现不同内容，无法建立唯一证据引用')
            issues.append({'record_id': record_id, 'event_id': event_id, 'code': 'duplicate_row',
                           'severity': 'warning', 'disposition': 'deduplicated', 'values': {}})
            continue
        records[record_id] = row
        events[event_id].append((revision, row))

    latest, usable = [], []
    reviewed = []
    superseded_count = 0
    for event_id, versions in events.items():
        revision = max(number for number, _ in versions)
        candidates = sorted((row for number, row in versions if number == revision), key=lambda row: row['记录编号'])
        superseded_count += len(versions) - len(candidates)
        row = candidates[0]
        record_id = row['记录编号']
        event_issues = []

        def issue(code, values, *, severity='error'):
            event_issues.append({'record_id': record_id, 'event_id': event_id, 'code': code,
                                 'severity': severity, 'values': values})

        if len(candidates) > 1:
            issue('ambiguous_latest_revision', {'candidate_record_ids': [r['记录编号'] for r in candidates]})
        if any(candidate[key] != row[key] for _, candidate in versions
               for key in ('学生编号', '节点编号', '材料编号')):
            issue('event_identity_changed', {'record_ids': [r['记录编号'] for _, r in versions]})
        identity_conflicts = list(event_issues)
        result = _validate_response(row, revision, students, items, nodes, issue)
        valid = all(entry['severity'] != 'error' for entry in event_issues)
        decision = decisions.pop(record_id, None)
        if decision is not None:
            if valid or decision['revision'] != revision:
                raise ValueError(f'{record_id}: 复核须指向当前最新版本且存在待复核异常')
            action = decision['action']
            changes = decision.get('changes', {})
            audit = {'record_id': record_id, 'event_id': event_id, 'revision': revision,
                     'action': action, 'reason': decision['reason'],
                     'original_issues': [entry['code'] for entry in event_issues],
                     'changes': {key: {'before': row[key], 'after': value} for key, value in changes.items()}}
            if action == 'correct':
                if identity_conflicts:
                    raise ValueError(f'{record_id}: 作答事件或版本冲突无法通过分值或主题更正解决')
                corrected = {**row, **changes}
                event_issues = []
                result = _validate_response(corrected, revision, students, items, nodes, issue)
                remaining = [entry['code'] for entry in event_issues if entry['severity'] == 'error']
                if remaining:
                    raise ValueError(f'{record_id}: 更正后仍有异常：{", ".join(remaining)}')
                valid = True
            reviewed.append(audit)
            result['review_action'] = action
        for entry in event_issues:
            if decision and decision['action'] == 'exclude':
                entry['disposition'] = 'excluded_by_review'
            else:
                entry['disposition'] = 'retained' if valid else 'needs_review'
        issues.extend(event_issues)
        result['validation_status'] = 'valid' if valid else 'needs_review'
        if valid and result['scoring_status'] == 'graded':
            usable.append(result)
        else:
            result['score'] = None
        latest.append(result)

    if decisions:
        raise ValueError(f'复核记录编号未匹配最新作答：{", ".join(sorted(decisions))}')
    counts = Counter(row['scoring_status'] or 'unknown' for row in latest)
    report = {
        'raw_rows': len(raw), 'unique_records': len(records), 'event_count': len(latest),
        'superseded_records': superseded_count,
        'latest_scoring_status_counts': {status: counts[status] for status in (*SCORING_STATUSES.values(), 'unknown')},
        'usable_count': len(usable), 'needs_review_count': sum(r['validation_status'] == 'needs_review' for r in latest),
        'unresolved_review_count': sum(r['validation_status'] == 'needs_review' and 'review_action' not in r for r in latest),
        'reviews': reviewed, 'review_input': review_input, 'response_source_sha256': response_sha256,
        'issue_counts': dict(Counter(entry['code'] for entry in issues)), 'issues': issues,
    }
    return IngestResult(list(students.values()), raw, latest, usable, report)
