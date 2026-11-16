import json
from hashlib import sha256
from pathlib import Path


REVIEWABLE_FIELDS = {'主题编号', '得分', '满分', '评分点得分', '评分状态'}


def read_reviews(path, response_sha256):
    if path is None:
        return {}, None
    path = Path(path)
    content = path.read_bytes()
    payload = json.loads(content.decode('utf-8-sig'))
    if not isinstance(payload, dict) or set(payload) != {'source_sha256', 'decisions'}:
        raise ValueError('复核文件必须包含 source_sha256 和 decisions')
    if payload['source_sha256'] != response_sha256:
        raise ValueError('复核文件的 source_sha256 与本批原始作答不匹配')
    if not isinstance(payload['decisions'], list):
        raise ValueError('复核文件的 decisions 必须是数组')

    decisions = {}
    for entry in payload['decisions']:
        required = {'record_id', 'revision', 'action', 'reason'}
        if not isinstance(entry, dict) or not required <= entry.keys() or entry.keys() - required - {'changes'}:
            raise ValueError('每条复核需提供 record_id、revision、action 和 reason，可附 changes')
        record_id = entry['record_id']
        if not isinstance(record_id, str) or not record_id.strip() or record_id in decisions:
            raise ValueError(f'复核记录编号为空、格式错误或重复：{record_id!r}')
        if type(entry['revision']) is not int or entry['revision'] < 1:
            raise ValueError(f'{record_id}: 复核版本必须是正整数')
        if not isinstance(entry['reason'], str) or not entry['reason'].strip():
            raise ValueError(f'{record_id}: 复核缺少依据')
        action = entry['action']
        changes = entry.get('changes', {})
        if action == 'exclude' and changes == {}:
            decisions[record_id] = entry
            continue
        if action != 'correct' or not isinstance(changes, dict) or not changes:
            raise ValueError(f'{record_id}: 支持 exclude（无更正字段）或 correct（需提供更正字段）')
        if changes.keys() - REVIEWABLE_FIELDS or any(not isinstance(value, str) for value in changes.values()):
            raise ValueError(f'{record_id}: 只可更正主题、评分状态及分值字段，值使用原 CSV 的字符串格式')
        decisions[record_id] = entry

    return decisions, {'file': path.name, 'sha256': sha256(content).hexdigest()}
