# P3 Assets：接口契约与阶段完成报告

## 依据、计划与范围

依据 PRD V1.1 §5.1–5.5、§6、§20，以及蓝图 V0.2 §2.1、§3、§5、§7、§14–15。
按用户要求只开发 P3；领域目录采用蓝图，不采用 PRD 的简化平铺目录。

已执行：定义资产契约 → 实现唯一性与引用校验 → Excel / JSON / YAML 导入 →
通过 Port / Adapter 实现 SQLite 持久化 → 单元测试与 P1/P2 回归 → 依赖审计及 R1–R4 自检。
冻结输入没有字段级完整 Schema，本文记录本阶段补充的正式契约与待确认项。

## 创建/修改文件

新增：

- `src/agent_test/domains/assets/{__init__,models,ports,service,api}.py`
- `src/agent_test/infrastructure/files/asset_files.py`
- `src/agent_test/infrastructure/storage/{__init__,sqlite_assets}.py`
- `tests/unit/assets/{conftest,test_models_service,test_files,test_sqlite}.py`
- `docs/p3-assets.md`

修改：

- `pyproject.toml`：增加 openpyxl 3.1.5。
- `tests/unit/test_dependencies.py`：允许文件/数据库 Adapter 所需依赖，Domain 仍禁止引用这些依赖。

P1/P2 模型、规则配置和既有测试保持原样；此前尚未提交的开发文件继续保留。

## 公开接口

统一入口：`agent_test.domains.assets.api`。

```python
validate_asset_set(payload: object) -> TestAssetSet
load_questions(source: QuestionSource) -> list[GoldenQuestion]
load_asset_set(source: AssetSetSource) -> TestAssetSet
save_asset_set(asset_set: TestAssetSet, repository: AssetSetRepository) -> None
get_asset_set(asset_set_id: str, repository: AssetSetRepository) -> TestAssetSet
list_asset_sets(repository: AssetSetRepository) -> list[AssetSetSummary]
```

Ports：

- `QuestionSource.read() -> list[dict[str, object]]`
- `AssetSetSource.read() -> dict[str, object]`
- `AssetSetRepository.save / get / list` 使用领域 DTO，不返回 SQLite Row、Workbook 或第三方实体。

实现：

- `ExcelQuestionSource(Path(...), sheet_name=None)`：读取问题行。
- `JsonAssetSetSource(Path(...))`、`YamlAssetSetSource(Path(...))`：读取完整资产文档。
- `SQLiteAssetSetRepository(Path(...))`：保存完整资产集、按 ID 读取、批量列出摘要。

不按扩展名动态加载模块；调用方显式选择实现。Domain 不依赖实现或文件/数据库库。

## 正式数据契约

所有模型拒绝未知字段。标识必须为非空且含非空白字符的字符串，不自动转换数字或修改业务值。
可空字段必须显式提供，除非下表注明默认值。JSON 值保留 null、0、false 的区别。
支持 Pydantic JSON Schema、JSON 序列化与往返验证。

| 模型 | 字段与约定 |
|---|---|
| GoldenQuestion | question_id、category、question、expected_behavior 必填；expected_metric / expected_scope / expected_grain / expected_time / note 必填可空字符串。行为复用 Canonical 的 ANSWER / CLARIFY / REJECT 枚举 |
| QuestionSet | questions 必填列表；question_id 唯一 |
| SnapshotRef | snapshot_id、kind、reference 必填；kind 为 snapshot / database / fixture；description、content_sha256 默认 null，非空校验和须为 64 位十六进制 |
| CanonicalCaseAsset | question_id 与 CanonicalTestCase；显式连接问题资产与语义 Case，不假设 question_id 等于 case_id |
| GoldenBaseline | baseline_id、question_id、snapshot_id、confirmed_by、confirmation_reference、source 全部必填；不能省略人工确认记录 |
| TestAssetSet | schema_version 固定字符串 `1`；asset_set_id、questions、snapshots、canonical_cases、golden_baselines、rules 全部必填 |
| AssetSetSummary | asset_set_id 与 question_count / snapshot_count / canonical_case_count / golden_baseline_count；计数为非负整数 |

GoldenSource 为判别联合，只接受以下四类：

| kind | 内容 |
|---|---|
| reference_sql | 必填 sql 字符串与 parameters JSON 对象；只保存，不执行 |
| reference_result | 必填 result JSON 值，允许显式 null |
| canonical_case | 必填已确认的 CanonicalTestCase |
| verified_version_result | 必填 agent_version_ref、verification_reference、result；版本引用为不透明来源标识，不分支处理 V4/V5 |

TestAssetSet 的结构校验：

- question_id、snapshot_id、canonical_cases 中 case_id、baseline_id 各自唯一。
- CanonicalCaseAsset.question_id 必须存在。
- 每个 GoldenBaseline 的 question_id 和 snapshot_id 必须存在。
- rules 复用 Rules 公开 RuleSet 契约，校验规则 ID，不筛选或自动批准规则。
- 不强制问题/Ground Truth 数量，不将 PRD 建议的 40–60 / 10–20 写成 Python 限制。
- 允许暂时为空的资产列表；空资产集不表示测试就绪或测试通过。

资产集不含目标 Agent 版本字段。Golden 的旧版本引用只表示真值来源，不将问题资产绑定到目标版本。
保存时重新验证完整模型，防止验证后被修改的无效数据进入存储。

## 导入与持久化行为

### Excel

表头为 GoldenQuestion 的九个字段，必须完整、唯一，列顺序可调整；未知列拒绝。
一个工作表时可省略 sheet_name，多工作表时必须显式指定，避免猜测。
整行技术空值被忽略，其余内容进入 Schema 校验。公式和错误单元格被拒绝，不执行公式。
预期时间等标识列要求文本，例如年份应写文本 `2026`，不会自动将数值或日期转成业务时间语义。
仅读取 PRD 问题资产，不自动构造 Canonical Scope/Time、Golden 或版本配置。

### JSON / YAML

读取一个完整 TestAssetSet 文档，顶层必须为对象；拒绝重复键、损坏文档、非法编码。
JSON 拒绝 NaN / Infinity；YAML 使用 SafeLoader 派生加载器，拒绝 Python 对象标签和多文档输入。
解码后统一进行领域 Schema 与引用完整性校验。

### SQLite

通过参数化 SQL 将整个已验证资产集存为一条 JSON 记录，单事务插入，不逐条保存子实体。
同 ID 重复保存抛出 AssetConflictError，原有数据保留；更新资产须明确使用新的资产集 ID。
本阶段没有覆盖、删除或自动更新 Golden 的接口。
list 通过一次批量 SELECT 获取资产文档并构建摘要，无循环逐条 IO 或 N+1 查询。
每次操作关闭连接；文件和工作簿也在完成或异常时释放。
读取时重新校验存储 JSON 和资产 ID；损坏内容不能作为有效 DTO 返回。

### 稳定错误

- AssetReadError：文件读取、格式解码、Excel 表头/单元格格式错误。
- AssetValidationError：解码后的资产不满足 Schema 或引用约束。
- AssetStorageError：SQLite 操作失败或存储内容损坏。
- AssetConflictError：同 ID 已存在。
- AssetNotFoundError：未找到资产集。

IO Adapter 及领域校验边界记录稳定错误信息，不记录原始问题、SQL、结果或配置值。
底层原因作为异常链保留用于诊断。直接构造模型或传入无效查询 ID 时可抛出 Pydantic ValidationError。

## 验证与结果

```sh
cd /workspace/Analysis_Agent_Test
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q -s
.venv/bin/python -m pip check
```

Unit Test：187 passed，包括 P3 新增 68 项和 P1/P2 的 119 项回归；无失败、跳过或预期失败。
覆盖：四类 Golden 来源、正常输入与 JSON 往返、空值/类型错误、唯一性、断裂引用、
确认记录缺失、规则审批保留、Excel 列重排/公式/错误/多工作表、损坏及恶意格式、
缺失文件、非法编码、SQLite 持久化重读、冲突保留原数据、参数化 ID、损坏数据、事务回滚及恢复。
文件和数据库测试均使用临时目录及明确标记的测试数据；未生成或批准生产 Golden。

Dependency Check：21 个生产模块的 AST 依赖图拓扑排序及边界检查通过。
主要方向：assets.api → assets.service / models / ports；assets.models → canonical.api / rules.api；
文件与 SQLite Adapter → assets.api；SDK 与 SQLite 只出现在 infrastructure。

## R1–R4 自检

- R1 PASS：只有 Schema、技术空值、类型、唯一性、引用和异常校验；无业务阈值、权重、筛选或指标组合硬编码。
- R2 PASS：资产业务源码归属 domains/assets；src 根目录无平铺业务文件。
- R3 PASS：21 模块 DAG 无环；跨域仅使用公开 api。
- R4 PASS：common 未创建，无业务引用；依赖审计保留此约束。
- 其他：无动态 import / eval / exec；Domain 无 infrastructure 依赖；外部库经过 Port / Adapter；
  不透传第三方实体，不静默吞 IO 异常，不自动批准规则或 Golden。

## 未完成项、风险与待确认项

1. P3 已实现范围无代码遗留；尚无真实问题集、Snapshot 数据及人工确认的 Golden 可导入，不能声明真实业务测试就绪。
2. 字段级资产契约、Excel 全表头约定、同 ID 禁止覆盖方式及 Golden 确认记录格式是本阶段的明确设计，需确认。
3. SnapshotRef 只保存引用与可选校验和；不访问外部资源、不计算或验证底层数据校验和。
   是否为同一固定数据源的运行期检查留给 Execution / Drift，不以同名 ID 代替内容验证。
4. 人工确认字段是已有确认记录的声明，不是身份验证或审批操作；本阶段不构建 Review 或权限系统，AI 不填造正式确认记录。
5. AgentVersion 与版本包解析属于 P4，当前不创建代理版本实体或映射。
6. 测试/执行、规则裁决、SQL 查询、Snapshot 管理服务、Web 上传页面和报告均不属于 P3。
7. P3 完成后停止，等待用户进入 P4。
