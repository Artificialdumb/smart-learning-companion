import csv
import io
import re
from pathlib import Path


DATA_PATH = Path('4_赛题数据') / '模拟学情数据'


def read_rows(source_dir, filename, fields, *, content=None):
    path = Path(source_dir) / DATA_PATH / filename
    if content is None:
        content = path.read_bytes()
    with io.StringIO(content.decode('utf-8-sig'), newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames or []
        missing = set(fields.split('|')) - set(headers)
        if missing or len(headers) != len(set(headers)):
            raise ValueError(f'{path}: 表头缺少字段或有重复字段。缺少 {sorted(missing)}')
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f'{path}: CSV 第 {reader.line_num} 行附近字段数量不符')
            rows.append(row)
        return rows


def index_rows(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if not value or value in result:
            raise ValueError(f'{key} 为空或重复：{value!r}')
        result[value] = row
    return result


def split_ids(value):
    return [part.strip() for part in re.split(r'[、,，;；]', value) if part.strip()]
