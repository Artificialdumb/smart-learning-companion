# 智能学伴

七年级数学学情分析项目。当前实现个人诊断和班级分析，从同一批经过校验的作答生成指标摘要、证据引用和同节点两班比较。

| 目录 | 内容 |
|---|---|
| `app/diagnosis/` | 个人作答覆盖、得分、评分点与证据不足提示 |
| `app/class_analysis/` | 两班共同题范围、名册人数、覆盖、得分和共性失分 |
| `tools/` | 本地 CSV 输入适配与 JSON 结果构建 |
| `fixtures/synthetic/` | 可复跑的合成题目、名册和作答 |
| `tests/` | 证据、修订归并与比较范围的验收测试 |
| [docs/integration.md](docs/integration.md) | Python 接口、输出字段与统计口径 |

## 运行

使用 Python 3.11+ 标准库。在仓库根目录运行：

```sh
python3 -m unittest discover -s tests -v
python3 -m tools.build_b --input fixtures/synthetic --out outputs
```

生成 `outputs/diagnosis.json` 和 `outputs/class_comparison.json`。`--out` 指向父目录已存在的新路径。重复运行可指定新的输出目录。

## 接入

`diagnose_students` 和 `compare_classes` 接收同批目录、完整名册和作答视图。也可使用 `python3 -m tools.build_b --input <批次目录> --out <输出目录>` 从标准化 JSON 输入直接构建结果。具备赛题 CSV 的团队成员可在本地用 `python3 -m tools.prepare_fixture --source <资料包目录> --out data` 准备调试输入。

仓库样例由合成数据编写。赛题资料、赛题作答及其分析结果保存在本地项目目录，使用范围遵循赛事规则。
