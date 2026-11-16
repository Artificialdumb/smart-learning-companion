# 智慧学伴

七年级数学学情分析与学习建议系统。个人诊断和班级比较使用同一批有效作答。教师可以打开作答证据、查看学习材料并调整学习计划。

## 本地运行

需要 Python 3.11 或更新版本。在仓库根目录执行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m app.cli build --source fixtures/synthetic
python -m uvicorn app.web.main:app --host 127.0.0.1 --port 8000
```

打开 [本地工作区](http://127.0.0.1:8000/)。如需使用本地赛题资料，改用 `python -m app.cli build --source "../赛题数据/赛题资料包"`。构建会打印批次编号。用 `python -m app.cli export --run-id <批次编号> --out outputs/成果包` 导出成果。运行测试用 `python -m unittest discover -s tests -v`。

| 目录 | 内容 |
|---|---|
| `app/diagnosis/` | 个人作答覆盖、得分、评分点与证据不足提示 |
| `app/class_analysis/` | 两班共同题范围、名册人数、覆盖、得分和共性失分 |
| `app/recommendations/` | 学习材料匹配、分步提示和教师调整校验 |
| `app/web/` | FastAPI 接口和本地网页 |
| `app/storage.py`、`app/cli.py` | SQLite 批次、教师调整、构建和导出 |
| `tools/` | CSV 开发适配与 B 模块独立构建 |
| `fixtures/synthetic/` | 可复跑的合成联调批次 |
| [联调说明](docs/integration.md) · [数据契约](docs/contracts.md) | 模块调用、字段、统计口径和演示复核 |

B 模块的独立入口仍可用 `python -m tools.build_b --input fixtures/synthetic --out outputs/b`。团队成员可用 `python -m tools.prepare_fixture --source <资料包目录> --out data` 准备标准化输入。赛题资料、赛题作答和其分析结果保存在忽略目录中，按赛题规则使用。
