# P4 Versioning：V4.6.1 分支交付

范围更新：用户随后确认 V4.0 不需要、V5.0 尚未完成。因此本轮 P4 以 V4.6.1 为目标，
该分支已交付并通过检查；V5.0 延后接入，不再作为进入 P5 的当前阻塞项。

## 输入、范围和计划

用户确认：上传的 V4.6.1 对应冻结需求中的 V4.1。实际版本 ID 保存为 V4.6.1，
V4.1 只作为 requirement_alias，不改写真实版本身份。
输入为 `super_ai_v4.6.1_src_cd05c99.zip`；归档 SHA-256 和选取文件的 SHA-256
记录在 `tests/fixtures/versioning/v461/provenance.json`。文件名中的 cd05c99 未被当作已验证的 Git commit。

依据 PRD V1.1 §2、§6–7、§8.7、§10、§20，以及蓝图 V0.2 §3、§5–7、§9、§14–15。

已执行计划：检查实际源码与数据契约 → 定义 Versioning 公共 DTO / Ports →
实现配置读取与能力投影 → 实现有显式绑定的 QueryTask / PlanStep 转换 →
真实输入及异常路径测试 → P1–P3 回归、依赖和 R1–R4 审计。

本轮覆盖 automotive ontology 和实际文本 QueryTask 3.1.0 结构。
上传包作为数据检查，未导入或执行其 Python 模块，未复制其业务计算实现。
未启动 Agent、数据库、AI 服务，也未提前开发 P5。

## 创建文件

- `src/agent_test/domains/versioning/{__init__,models,ports,api}.py`
- `src/agent_test/infrastructure/version_adapters/__init__.py`
- `src/agent_test/infrastructure/version_adapters/v4/{__init__,package,capability,task}.py`
- `config/versioning/v461.yml`
- `tests/unit/versioning/{conftest,test_capability,test_plan}.py`
- `tests/fixtures/versioning/v461/`：源包原样复制的 7 份 YAML、2 份 QueryTask JSON 和 provenance.json
- `docs/p4-versioning.md`

既有 Canonical / Rules / Assets 实现和依赖声明未修改。本阶段不增加通用注册器、Factory 或动态模块加载。

## 公共接口和正式契约

领域入口：`agent_test.domains.versioning.api`。

| 契约 | 必填内容 |
|---|---|
| AgentVersion | version_id、requirement_aliases、source_reference、source_sha256、semantic_version |
| VersionPackage | version、documents（解码后的 JSON 兼容源文档，仅位于版本边界） |
| CapabilityDeclaration | capability_id、declared_status、status_basis、included_in_canonical、limitations、source_metadata |
| CapabilityNormalization | capabilities: CanonicalCapabilitySet；declarations: 全部源声明；纳入标记与 Canonical ID 集合必须一致，声明 ID 唯一 |
| VersionPackageSource | read() → VersionPackage |
| CapabilityAdapter | normalize(VersionPackage) → CanonicalCapabilitySet；inspect(VersionPackage) → CapabilityNormalization |

领域 DTO 拒绝未知字段并校验标识与 SHA-256 格式。source_metadata 中的版本字段只用于审计，
不能透传给测试核心作为语义模型。源 catalog 可保留 JSON 兼容扩展字段，适配所读取的字段有类型校验；
本阶段不宣称重新实现了被测 Agent 的整个 ontology 编译器。

具体实现由调用方静态选择：

```python
mapping = V461Mapping.load(Path("config/versioning/v461.yml"))
package = V461DirectorySource(ontology_root, version, mapping).read()
report = V461CapabilityAdapter(mapping).inspect(package)
capabilities = report.capabilities

case = V461PlanAdapter(mapping).normalize(
    case_id=case_id,
    question=question,
    expected_behavior=expected_behavior,
    steps=exported_plan_steps,
    bindings=resolved_bindings,
)
```

Plan Adapter 位于 Version Adapter 内；expected_behavior 必须显式传入，
不根据版本、能力状态、AI 输出或题号推断 ANSWER / CLARIFY / REJECT。

## 真实输入发现与能力投影

1. 源包有多个同名能力表。使用 `repo1/domains/automotive/ontology/` 下的 V4.6 声明，
   不使用归档根目录和其他旧副本。源码 `repo4/.../recall/capability.py`、`plan/binder.py`
   明确读取 Repo1 声明中的 task_intent / fanout / analysis 等字段。
2. package.yml 的 semantic_version 为 4.0.0，它是 ontology 版本，不能替代用户确认的 Agent V4.6.1。
3. 真实能力声明 40 条：AVAILABLE 26、PARTIAL 4、OUT_OF_SCOPE 9、CALIBRATION_PENDING 1。
4. 配置 `exposed_statuses: [AVAILABLE]` 默认投影 26 条 Canonical 能力；全部 40 条声明及原状态均保留。
   该选择是配置，不是硬编码，也不把声明状态改成运行时验证结果。
5. metric_refs / link_refs / metric.measured_at / base_metric / supported_dimensions / time_op
   提供显式语义轴；引用缺失、重复 ID、基指标环或未知 fanout 会返回稳定错误。
6. year_month 在多个指标的 supported_dimensions 中有明确声明，但不在 dimensions.yml。
   通过配置 additional_dimension_ids 显式登记源 ID，不推断额外时间业务规则。
7. subjects 只来自明确的 measured_at / 基指标 / Link 起点，缺失时不填“默认车型”。
   dimensions 是声明维度的并集，不代表其与所有指标可以任意组合。
8. 多步标记来自源 fanout 或真实 recipe 步骤数量；不根据 S1–S12 名称编造步骤。
   recipe 表达式只保留在源文档，不求值或执行。

源声明没有完整给出每条能力的过滤轴和集合操作表，因此投影中的 filters / set_ops 为空，
limitations 明确说明“不完整声明”，不能将空列表解释成运行时已证实不支持。
time_ops 仅提取显式指标算子，不声称穷举所有合法时间组合。
尚未重新计算签认降级或运行期可用性；这些不是结构适配器的业务职责。

## QueryTask / PlanStep 语义契约

源公共合同依据：`repo3/src/vida_runtime/contracts/task.py`；PlanStep 依据
`repo4/src/vida_agent/plan/binder.py`，动态集绑定依据 `plan/recipes.py`。

V461SemanticBindings 显式提供 metric、subject、subject kind hint、dimension、attribute、
filter value、relation、entity、time、ObjectSet 类型，以及必要的参数和集合身份绑定。
文本只表示未裁决的输入；绑定缺失或不一致时拒绝转换，不做模糊召回、默认别名或 AI 猜测。
绑定在单元测试中是测试数据，不被自动升级为 Golden 或人工批准真值。

输出全部为 CanonicalTestCase / CanonicalStep 及其嵌套模型。
P1 的 operation.parameters 已允许 JSON 参数，P4 明确以下**跨版本通用参数约定**，不加入源字段名：

| 参数 | 契约 |
|---|---|
| metrics | 完整 Canonical 指标 ID 列表；单指标同时填顶层 metric，多指标时顶层 metric 为 null，不只取第一项 |
| scopes | 完整 SemanticScope 列表；单 Scope 同时填顶层 scope，多 Scope 时为 null |
| output | 统一输出类别，例如源 group_rows 映射为 table |
| arguments | 仅保存配置指定键名及显式绑定后的 JSON 参数；未知源参数拒绝，不原样透传 |
| limit / percentiles | 已通过源合同类型/范围校验的输入参数，不执行排名或分位计算 |
| order | by、已解析 key、direction；排序方向保留 |
| traversal | 统一 direction（forward / reverse）、已映射 scope、target_ids、project_to_target；relation 模型保存治理边的端点，方向单独保留 |
| comparison | operands（operand_id + 完整 CanonicalSemanticModel JSON）、pairs、mode；每侧筛选、否定和时间分别保留 |
| subject_binding | source_object_set_id；表示由前序集合注入主体名称，不等同于静态集合成员过滤 |
| filter_binding | source_object_set_id + attribute / dimension 字段映射；不在适配阶段读取对象值 |
| result_included | 源 final 标记，保存该步骤是否贡献最终结果 |
| step_ids | 多步根 operation 使用 sequence，显式保留步骤列表顺序；各步语义分别位于 steps |

这些参数是阶段内定义的 Canonical 通用约定；后续 Evaluation 必须读取完整语义，
尤其不能把多指标时的顶层 null 当作“无指标”。未修改 P1 数据模型，字段级约定列为待确认项。

其他结构保证：

- ne / not_in 通过配置转换成基础操作符与 negated=true；区间端点和集合运算操作数保持顺序。
- SetOperation 的 operand_set_ids 要求显式绑定，不能把目标实体 ID 冒充 ObjectSet ID。
- 消费集合必须匹配原任务及动态注入字段；集合必须由前序依赖闭包中的步骤产生，或显式声明为外部集合。
- 拒绝步骤环、前向引用、重复步骤/任务 ID、重复集合生产者和不一致的 emits。
- 时间文本必须有显式 SemanticTime 绑定；已给出的 grain、起止月份、算子和上市月数须保持一致。
  时间 grain 不被误写成实体 grain；源未提供实体 grain 时保留 null。
- security_context、路由、题号、展示标签、purpose 和 view 不进入 Canonical。
  它们不被用作业务正确性判定；执行审计和呈现由后续领域负责。

## 错误、IO 和依赖

VersionPackageError：文件读取、YAML 解析、配置或包身份/语义版本校验失败。
VersionNormalizationError：输入不符合受支持结构、引用缺失、绑定缺失、语义无法无损转换。
两类错误在边界转换并记录稳定日志，不输出原始参数、源代码或账号上下文；异常链保留诊断原因。
使用 SafeLoader 派生加载器，拒绝重复键和 Python 对象标签，包文件路径不得逃出显式 ontology_root。
SHA-256 provenance 证明本次输入与夹具一致，不声称重放运行期认证或外部数据库。

依赖方向：versioning.api → versioning.models / ports；models / ports → canonical.api；
V4 Adapter → versioning.api / canonical.api / PyYAML。
无 Domain → infrastructure，无 SDK / ORM / 数据库实体进入核心，无动态 import / eval / exec。

## 验证结果

```sh
cd /workspace/Analysis_Agent_Test
.venv/bin/python -m pytest -q -W error
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q -s
.venv/bin/python -m pip check
```

- 250 passed：P4 新增 63 项，P1–P3 回归 187 项；无失败、跳过、预期失败或测试警告。
- 30 个生产模块的依赖 DAG 与领域边界审计通过；pip check 通过。
- 原始解压目录独立读取与夹具校验：9 个文件 SHA-256 一致，40 条声明、26 条默认投影能力。
- 两份真实 QueryTask JSON 已验证；多步/比较/集合测试使用实际合同构造的测试样例，
  不宣称这些样例是 Agent 实际执行轨迹或已确认业务真值。
- 验证范围是结构转换与语义保留，不是 Agent 端到端运行或业务数值正确性。

## R1–R4 自检

- R1 PASS：状态筛选、fanout 映射、否定转换、输出与操作词汇、默认值和补充维度 ID 均在 YAML；
  Python 分支只做输入 Schema / 引用 / 表达完整性校验及技术转换，不带阈值、权重或指标特例。
- R2 PASS：业务契约在 domains/versioning，版本差异在 infrastructure/version_adapters/v4，src 根目录无业务文件。
- R3 PASS：30 模块依赖无环，跨域只使用公开 api。
- R4 PASS：common 无业务依赖，本阶段未创建 common。

## 阶段状态与待确认项

V4.6.1 分支的本次实现和检查已完成，满足用户调整后的本轮版本范围：

1. V4.0 已移出范围；V5.0 输入延后提供，本次源码不能证明 V5.0 的结构，不生成猜测实现，
   也不把 V4.6.1 的 ontology semantic_version=4.0.0 当作一个 V4.0 Agent。
2. 当前只验证 automotive 行业包；未宣称 retail 或其他旧副本已适配。
3. 缺少真实已裁决的 QueryTask/PlanStep 导出及对应业务确认语义；现阶段结构保留有测试证据，
   尚无真实业务映射验收。可提供脱敏导出和人工确认语义继续验证，无需 API 密钥。
4. 多指标、多主体、比较与动态集合绑定的中性 operation.parameters 约定需确认；
   P5 不能忽略这些内容。能力声明的 filters / set_ops 完整性仍需真实声明补充。
5. 未实现 Agent 调用、签认重算、SQL 执行、测试生成、Evaluation、Drift 或 UI。

根据上述用户范围调整继续 P5；V5.0 在真实版本包与代表性语义样例提供后另行验证。
