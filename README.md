# 智慧学伴

七年级数学学情分析与学习建议系统。个人诊断和班级比较使用同一批有效作答。教师可以打开作答证据、查看学习材料并调整学习计划。

每个指标给出**掌握度（得分比例指数）**：每条有效作答按得分比例计一次证据，累计本次及更早测验，给出平滑后的指数、90% 区间和等级，有效作答少于 3 条时标注“证据不足”。该指数描述经平滑的得分比例，结合有效作答条数与区间阅读，见[证据权重说明](docs/evaluation/掌握度证据权重说明.md)。

个人诊断中，有失分证据的指标提供两个入口：**错因追问**用 3–4 道独立小题检查概念、计算和条件理解，按本次失分评分点排序，并在已定位出错步骤时用学生本人的过程生成核对题，保存作答及待核查线索；**查看补学路径**沿目录中的前置知识关系排列复习与补测步骤，并链接原始证据、学习卡和教材。补充追问独立保存，原测验和教师计划分别保留版本。

## 本地运行

需要 Python 3.11 或更新版本。在仓库根目录执行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m app.cli build --source fixtures/synthetic
python -m uvicorn app.web.main:app --host 127.0.0.1 --port 8000
```

打开 [本地工作区](http://127.0.0.1:8000/)。如需使用本地赛题资料，把资料包放入 `data/` 后运行 `python -m app.cli build --source data/赛题资料包`，也可传入其他本地路径。构建会打印批次编号。用 `python -m app.cli export --run-id <批次编号> --out outputs/成果包` 导出成果。运行测试用 `python -m unittest discover -s tests -v`。A 的赛题数据回归使用 `data/赛题资料包`，也可用环境变量 `STUDY_CONTEST_SOURCE` 指定原始资料包路径。

## 团队目录与调用入口

```text
smart-learning-companion/
├── app/
│   ├── catalog/              # A · 课程、题库与材料目录
│   ├── ingestion/            # A · 修订归并、质量校验与复核
│   ├── diagnosis/            # B · 证据诊断、指数、追问与补学路径
│   ├── class_analysis/       # B · 共同题比较与共性失分
│   ├── recommendations/      # B · 活动生成、材料与提示校验
│   ├── web/                  # C · FastAPI、权限与网页
│   ├── cli.py                # C · 构建与成果导出
│   ├── storage.py            # C · 批次、事务与交互版本
│   └── rules.json            # 批次生效规则
├── docs/
│   ├── design/               # 需求、方案与模块职责
│   ├── interfaces/           # 数据契约、HTTP与联调
│   ├── evaluation/           # 证据权重与教师评价
│   └── delivery/             # 提交清单、依赖与来源
├── fixtures/synthetic/       # 合成输入与调整样例
├── tests/                    # 模块、接口与回归测试源码
├── tools/                    # B独立构建、数据适配、模拟与评价
├── .github/workflows/        # Python 3.11—3.13自动回归
├── pyproject.toml            # 安装、依赖和数据文件声明
├── requirements-lock.txt     # 运行与测试依赖锁定
└── requirements-docs-lock.txt # PDF生成工具依赖锁定
```

[方案与模块职责](docs/design/问题界定与方案说明.md)、[数据契约](docs/interfaces/contracts.md)、[联调说明](docs/interfaces/integration.md)及[完整文档索引](docs/README.md)提供协作入口。构建、网页和导出共用app中的业务函数，tools通过既有模块完成独立运行。

B 模块的独立入口为 `python -m tools.build_b --input fixtures/synthetic --out outputs/b`。用 `python -m app.a_pipeline --source data/赛题资料包` 可单独生成 A 的标准化快照。赛题资料、赛题作答和其分析结果保存在忽略目录中，按赛题规则使用。

默认是本机演示模式。共享服务须配置账号权限和 HTTPS，见[共享服务配置](docs/interfaces/integration.md#共享服务配置)。
