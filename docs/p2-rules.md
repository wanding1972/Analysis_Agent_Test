# P2 Rules：契约、边界与阶段报告

## 依据与计划

依据 PRD V1.1 §5.5、§8.4–8.6、§13–14、§20，蓝图 V0.2 §3–4、§7–9、§14–15，
以及用户的 R1–R4 和按阶段开发约束。

已执行计划：

1. 定义规则元数据、人工批准声明、兼容表、有限断言及输入/输出 DTO。
2. 实现配置驱动的纯检查函数，不创建 Evaluator 或通用规则引擎。
3. 通过 Port / YAML 文件 Adapter 加载和验证配置。
4. 保存 PRD 候选规则，测试正常与主要异常路径，回归 P1 并执行依赖审计。

## 文件清单

新增：

- `src/agent_test/domains/rules/{__init__,models,ports,service,api}.py`
- `src/agent_test/infrastructure/__init__.py`
- `src/agent_test/infrastructure/files/{__init__,rule_config}.py`
- `config/{semantic_rules,properties,metamorphic}.yml`
- `tests/unit/rules/test_rules.py`
- `docs/p2-rules.md`

修改：`pyproject.toml`（增加 PyYAML 6.0.3）、`tests/unit/test_dependencies.py`。
P1 的 Canonical 实现及其测试保持原样。当前仓库仍包含上阶段尚未提交的文件，本阶段未删除或覆盖它们。

## 公开接口

领域入口：`agent_test.domains.rules.api`。

```python
load_rules(source: RuleConfigSource) -> RuleSet
check_rule(rule: TestRule, inputs: RuleInputs) -> RuleOutcome
check_compatibility(
    semantic: CanonicalSemanticModel,
    rules: list[CompatibilityRule],
    context: CompatibilityContext,
) -> list[RuleOutcome]
```

`RuleConfigSource.read() -> dict[str, object]` 是 IO Port；读取失败须抛出 `RuleConfigError`。
文件实现是 `infrastructure.files.rule_config.YamlRuleConfigSource(Path(...))`。
Domain 不引用该实现或 PyYAML。

外部数据先经对应模型的 `model_validate` / `model_validate_json` 校验。
检查入口重新验证传入 DTO，拒绝验证后被改坏的输入。
输入 Schema 错误抛出 `ValidationError`，配置读取、解析和 Schema 错误转换成稳定的
`RuleConfigError` 并在对应边界记录日志，不记录原始配置或事实值。

### 数据契约

所有模型拒绝未知字段。业务标识使用非空字符串，无内置业务值白名单。
规则格式标记、断言类型、结果状态及字段名属于 Schema 枚举。

| 契约 | 必填字段及意义 |
|---|---|
| RuleSet | schema_version 固定为字符串 `1`；compatibility_rules、test_rules 两个列表；整个集合内 rule_id 唯一 |
| RuleMetadata | rule_id、description、approval、approved_by；approval 为 proposed / approved / retired，approved 时 approved_by 不能为 null |
| CompatibilityRule | Metadata + family、when、require；require 非空；when 和 require 为 AxisConstraint 列表 |
| AxisConstraint | axis、非空 allowed 标识列表 |
| TestRule | Metadata + category（property / metamorphic）、preconditions（事实名 → 预期 JSON 值）、assertion |
| RuleInputs | facts：事实名 → JSON 值；布尔、数值、null、数组、对象保持类型；拒绝非有限数值 |
| CompatibilityContext | 可空 join_cardinality、aggregation、denominator_scope；由调用方提供，不从版本或数据中猜测 |
| RuleOutcome | rule_id、status、reason；不代表最终 Case 或四层 Evaluator 判定 |

八个 family 与蓝图 §8.2 一致：metric_scope_rules、metric_grain_rules、
metric_dimension_rules、metric_time_rules、join_cardinality_rules、aggregation_rules、
denominator_rules、relation_rules。

可选语义轴是 metric、subject、grain、dimensions、time_op、filters、relations、set_ops、
operation 及 Context 的三个字段。subject 来自 scope.subject，filters 指过滤字段名；
本阶段不推断 Join 或分母语义。版本特有 axis（route / shape / version 等）不被接受。

### 有限断言契约

所有参数均为配置必填项，没有隐藏的业务阈值、容差或字段选择。
事实绑定是顶层键名，不支持脚本、嵌套路径表达式、动态函数或动态模块。

| kind | 配置参数 | 执行含义 |
|---|---|---|
| numeric_range | value、minimum、maximum、include_minimum、include_maximum | 读取数值事实，与配置边界比较；拒绝 bool、字符串和 null |
| count_limit | items、limit | 数组长度不超过另一个事实中的非负整数；N 不在 Python 内指定 |
| subset | subset、superset | 左侧成员均出现在右侧，支持 JSON 对象成员 |
| disjoint | left、right | 两数组无相同成员 |
| distinct | left、right | 类型敏感的 JSON 不同，明确区分 null、0、false |
| sum_equals | parts、total、absolute_tolerance | 数值数组总和与总量差的绝对值不超过配置容差；使用 Decimal 避免二进制浮点加法引入误差 |
| semantic_equal | left、right、非空 fields | 两个输入均校验为 CanonicalSemanticModel，只比较配置指定的 Canonical 字段 |

这些是固定、有限的数学/结构操作实现，具体使用哪种检查、检查哪些事实、
何时适用及业务取值均由 YAML 指定；不是新增业务 DSL 或可扩展规则框架。
semantic_equal 比较 P1 基础语义模型，不在 P2 比较执行 Trace、步骤执行或 Evidence。

### 执行与结果

| 场景 | status / reason |
|---|---|
| 未批准或已退役 | blocked / not_approved |
| 适用条件缺少输入、断言缺少事实或兼容性轴缺失 | blocked / missing_input |
| 适用条件不匹配 | skipped / not_applicable |
| 事实类型不适合断言或语义事实不符合 Canonical Schema | blocked / invalid_input |
| 条件适用且断言满足 | passed / satisfied |
| 条件适用且断言不满足 | failed / violated |

审批门禁先于条件和断言检查。所有 preconditions 必须存在且匹配才能执行；
不存在与显式 null 不等同。兼容规则 when 条件须全部满足，require 中每轴的所有实际值须在 allowed 中。
空轴返回缺失输入，不依靠空集合真值推断兼容。多个规则各自返回结果，不隐式决策冲突优先级。
空规则列表返回空结果，不视作兼容性检查通过。

check_compatibility 检查传入的一份语义；多步场景须由后续调用方显式逐步骤调用，P2 不做流程编排。
完整月份/分组、同源、同排序等前提均在配置中声明，由可信调用方提供事实；P2 不推断完整性。

## 当前配置与审批边界

- `semantic_rules.yml`：Schema 已可用，真实兼容表为空；未提供真实指标、Ontology、Join 或分母配置。
- `properties.yml`：7 条 PRD 候选，包括范围、TopN、ObjectSet、unknown/zero、交集和差集。
- `metamorphic.yml`：5 条候选，包括年月汇总、分组汇总、Top10/Top20、过滤子集和语义等价。
- 所有候选均为 proposed，approved_by 为 null；本阶段没有自动批准任何正式规则。
- 安装率候选明确使用 percent 单位与 [0, 100]，不是假设真实 Agent 输出采用该单位。
- 汇总候选容差显式配置为 0，仅是待确认示例，不构成所有业务指标的容差政策。

P2 中 approved_by 仅为已有人工审批记录的声明，不是身份认证或审批页面。
不得由 AI 填造审批记录；可信配置管理和 QA 操作在后续 Assets / Review / Application 阶段连接。
测试中的 test-fixture-only 审批仅存在于内存测试数据，不回写 YAML。

## 验证命令与结果

```sh
cd /workspace/Analysis_Agent_Test
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q -s
.venv/bin/python -m pip check
```

本阶段完整测试：119 passed（P1 的 33 项 + P2 新增 86 项），无失败、跳过或预期失败。
覆盖七类断言的正常及异常路径、八类兼容表、审批门禁、条件、空规则集、Schema 错误、
重复 ID、修改配置改变结果、配置绑定、JSON 往返、禁止 Python YAML 标签、重复 YAML 键、
损坏/多文档 YAML、文件缺失及编码错误。三个实际 YAML 文件均经加载和 Schema 验证。

依赖方向：rules.api → rules.service / models / ports；rules.service → canonical.api；
YAML Adapter → rules.api / PyYAML。生产模块 DAG 与边界审计通过。
Domain 无文件/网络/数据库 IO；只有文件 Adapter 依赖 PyYAML。

## R1–R4 自检

- R1 PASS：Python 无具体指标组合、筛选值、权重或业务阈值。断言固定操作实现与业务配置分离。
- R2 PASS：业务源码只在明确领域子包，src 根目录无业务文件。
- R3 PASS：AST 依赖图拓扑排序通过，无循环导入；跨域只依赖公开 api。
- R4 PASS：未创建 common 业务依赖；审计禁止 common 引用领域、应用、呈现或基础设施。
- 其他：无动态 import / eval / exec；无 SDK 或存储实体透传；YAML 使用 SafeLoader 派生加载器；
  IO 错误有稳定转换和日志；无逐条 IO 或 N+1 查询。

## 未完成项、风险与待确认项

1. P2 已实现范围无代码遗留。生产正式规则仍需真实兼容表及人工审批；不声称正式业务规则已经可执行。
2. 冻结输入未规定 Rules 字段级 Schema，本文是实现的正式接口提案；需确认字段绑定、条件和缺失输入约定。
3. Blueprint 同时列举 Generation / Drift / Review 策略，但其专属结构与执行分别留待 P6 / P8 / P9；
   本阶段不创建伪实现或提前引入这些领域。
4. P1 的 CanonicalCapability 不含 Join、聚合和分母元数据，故通过显式 CompatibilityContext 传入；
   未借机修改 P1 契约或猜测值。
5. 未实现 Evaluation、版本 Adapter、AI 调用、Agent 执行、QA 界面或通用规则引擎。
6. P2 完成后停止，等待用户进入 P3。
