# P5 Evaluation：接口契约与阶段报告

## 当前范围与实施计划

用户最新确认：V4.0 不需要，V5.0 尚未完成；本轮以 V4.6.1 为目标，V5.0 延后接入。
P4 的当前范围记录已同步更新。P5 不包含版本分支，接收 Canonical 数据与资产/规则公开 DTO。

依据 PRD V1.1 §5.3–5.5、§8.1、§8.4–8.8、§12–14、§20，蓝图 V0.2 §3、§6.5、§7–9、§14–15。

已执行计划：定义四层输入/策略/结果契约 → 配置驱动的 Semantic / Plan 比较 →
Golden / Property / Metamorphic Evidence 判定 → 结构化 Answer Claim 检查 →
异常及回归测试、依赖审计、R1–R4 自检。本阶段不进入 P6 Generation。

## 文件清单

新增：

- `src/agent_test/domains/evaluation/{__init__,api,models,ports,checks,semantic,plan,evidence,answer,service}.py`
- `src/agent_test/infrastructure/files/evaluation_config.py`
- `config/evaluation.yml`
- `tests/unit/evaluation/{conftest,test_evaluation}.py`
- `docs/p5-evaluation.md`

修改：

- `domains/rules/{models,service,api}.py`：为多层复用补充 json_equal / unordered_equal 两种有限断言；
  不复制比较实现，不增加业务规则或通用 DSL。
- `tests/unit/test_dependencies.py`：禁止 Evaluation 依赖 Versioning / Execution 等外围领域。
- `docs/p4-versioning.md`：仅同步用户确认的版本范围。

未修改已有 Canonical、Assets 或 V4 Adapter 实现；未新增运行依赖。

## 正式接口

公开入口：`agent_test.domains.evaluation.api`。

```python
load_policy(source: EvaluationPolicySource) -> EvaluationPolicy
evaluate(
    request: EvaluationRequest,
    reference_reader: ReferenceEvidenceReader | None = None,
) -> TestResult
```

PRD 的 test_case / trace / approved_rules / golden_baseline 参数通过稳定 EvaluationRequest 聚合。
此处 Observation 是归一化观察数据，不是提前实现 P7 AgentTrace，也不是 SDK 或 ORM 实体。
外部输入先经 model_validate 校验，evaluate 再验证完整 DTO。

### 输入契约

所有模型拒绝未知字段和非有限数值；标识为非空字符串。缺失与显式 null 不等同。

| 模型 | 字段 |
|---|---|
| EvaluationRequest | test_case: CanonicalTestCase、question_id、snapshot_id、observation、approved_rules: RuleSet、golden_baseline: GoldenBaseline 或 null、policy；related_evidence 默认为空映射 |
| Observation | case_id、snapshot_id、semantic: CanonicalSemanticModel 或 null、steps / step_dependencies 或 null、evidence 或 null、answer 或 null |
| EvidenceBundle | result: JSON 值（可为 null）、references: EvidenceReference 列表 |
| EvidenceReference | evidence_id、path（字面 JSON 键/非负数组索引列表）、conditions: CanonicalSemanticModel 或 null；step_id 默认 null |
| AnswerObservation | behavior: ExpectedBehavior、claims、claims_complete: 严格 bool 或 null、conditions: CanonicalSemanticModel 或 null |
| AnswerClaim | claim_id、evidence_id 或 null、value: JSON 值、conditions: CanonicalSemanticModel 或 null |
| RelatedEvidence | snapshot_id、bundle: EvidenceBundle |

Evidence ID 和 Claim ID 各自唯一。EvidenceReference 不复制一个可与真实结果不一致的 value：
数值通过 result + path 直接读取。空 path 指整个 JSON 结果，不支持通配符、过滤表达式或函数。
引用的 step_id 非空时，条件与预期 Canonical 步骤比较；否则与预期根语义比较。

### 策略契约

EvaluationPolicy 必填 schema_version、approval、approved_by、precedence、semantic、plan、evidence、answer。
approved 状态要求人工批准引用；仓库默认配置为 proposed，测试批准记录仅存在于夹具。
precedence 必须完整且唯一地列出 passed / failed / blocked / skipped；默认配置 failed、blocked 优先。

四层策略均显式配置 behaviors 与 failure_code，决定适用行为和错误分类。

- SemanticPolicy.fields：Canonical 语义字段 → 比较类型。
- PlanPolicy.fields：steps / step_dependencies → 比较类型；validate_structure 为严格布尔值。
- EvidencePolicy：require_golden、golden_comparison、rule_bindings、check_reference_conditions、
  reference_condition_comparison、condition_fields 均必填。
- AnswerPolicy：checks、condition_fields、required_claims_complete 均必填；check 包含 kind、behaviors、comparison。

比较类型：json_equal 为类型敏感的精确 JSON 相等；unordered_equal 为保留重复数量的无序数组相等。
unknown/null、0、false 不混同。不自动设置数值容差或单位转换；数值容差可由已批准的 Sum/其他正式规则明确配置。

## 四层行为

### L1 Semantic → SEMANTIC_ERROR

逐项比较配置指定的 Metric、Scope、Grain、Dimension、Time、Filter、Relation、Set Operation、Operation。
operation 为完整 JSON 比较，覆盖 P4 的多指标、多主体、比较操作数与动态集合参数，不能只比较顶层 metric。
人工确认的 Canonical Golden 存在时，其语义和预期行为作为真值，候选 Case 不能覆盖 Golden。
缺失实际语义返回 blocked。

### L2 Plan → PLAN_ERROR

按照配置比较完整 Canonical steps 和依赖。默认步骤有序、依赖无序。
完整步骤中包含 ObjectSet 输入/输出、Scope、操作和参数，可发现对象集丢失或范围变化。
启用结构检查时，使用 Canonical Schema 校验实际图，发现未知步骤引用、前向依赖和环等结构错误。
缺失计划或零步骤返回 blocked，不以空列表相等证明计划正确。
比较输入须使用稳定的 Canonical 符号 ID；运行期 UUID/别名应在版本/执行归一化边界处理。

### L3 Evidence → EVIDENCE_ERROR

- ReferenceResult / VerifiedVersionResult：与归一化实际 result 按配置比较。
- ReferenceSQL：通过 ReferenceEvidenceReader Port 获取已固定 Snapshot 的归一化 JSON 结果；领域不执行 SQL。
- Canonical Golden：用于 L1，不被当作数值真值。
- Property / Metamorphic：按 policy.rule_bindings 选择正式 RuleSet 中的规则，使用公共 check_rule。
- Evidence 引用条件：按配置与预期根/步骤的条件比较；数值碰巧相同不能掩盖 Scope/Filter 丢失。

有限事实来源：result（当前结果路径）、semantic（实际 Canonical 语义路径）、
related（显式相关结果路径）、literal（配置中的 JSON 值）。不接受执行任意代码的表达式。
related 的 Snapshot 必须与本次一致，缺失事实、未批准规则、无可用 Reference Reader 均阻塞。
没有数值 Golden 且没有适用正式规则时返回 blocked；规则全部 skipped 也不能构成通过依据。
条件引用检查本身不算数值判定 Oracle。

### L4 Answer → ANSWER_ERROR

按配置选择 behavior、claims_complete、claim_values、claim_conditions、answer_conditions 检查：

- 预期与实际 ANSWER / CLARIFY / REJECT 行为相等。
- 每条 Claim 必须绑定有效 Evidence ID；不存在的引用属于 unbacked_claim。
- Claim value 必须匹配该引用在实际 result 中的值；不是在整个结果里搜索“出现过这个数字”。
- Claim 条件与引用 Evidence 条件比较，回答整体条件与预期语义比较。
- unknown/null 被写成 0 时，类型敏感的值比较失败。
- claims_complete 为 null / 不满足配置要求时阻塞，不能宣称完整检查了自由文本数字。

本阶段不实现 NLP/LLM Claim 抽取，不凭结构化 Claim 列表推断原始文本完整性。
运行期调用方必须由可信归一化/确定性提取提供覆盖声明；尚未完成 P7 接入前，不声称真实回答已完成检测。

## 上下文、结果和错误

执行前先检查 policy 批准状态、case_id、Snapshot、Golden 的问题/Snapshot 引用。
不匹配则四层 blocked，且不调用 Reference Reader。
缺少输入与确实失败分开记录；不会用异常吞掉一个失败判定，也不把所有层归为单一错误。

TestResult：case_id、snapshot_id、status、完整四层 LayerResult。
LayerResult：layer、status、failure_code 或 null、CheckResult 列表。
CheckResult：check_id、status、reason、expected、actual。配置决定汇总优先级，保留全部分层失败。
默认已发现失败优先于阻塞；blocked 不等于业务错误；skipped 只表示配置明确不适用。
默认 CLARIFY / REJECT 跳过前三层，但仍检查实际行为、Claim 覆盖和 Evidence 支撑。

EvaluationConfigError 表示策略读取/Schema 错误；文件 Adapter 复用现有安全 YAML 解析器。
ReferenceEvidenceError 由 IO 实现返回；领域记录稳定信息并给出 blocked，不泄漏原始诊断内容。
Reference Reader 的 SDK/非法 JSON/非有限数值输出被拒绝。没有注册真实数据库实现或默认连接地址。
普通外部 DTO Schema 错误抛出 ValidationError，调用方不得将其包装成通过。

## 验证

```sh
cd /workspace/Analysis_Agent_Test
.venv/bin/python -m pytest -q -W error
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q -s
.venv/bin/python -m pip check
```

- 320 passed：P5 新增 70 项，P1–P4 回归 250 项；无失败、跳过、预期失败或测试警告。
- 覆盖四层正常与主要异常路径、九种语义变化、计划结构/顺序/依赖、Golden、Reference Port、
  Property / Metamorphic、同 Snapshot、缺失/跳过规则、Claims 条件和 unknown/zero、策略审批与错误输入。
- 41 个生产模块的 DAG 与领域边界审计通过；pip check 通过。
- Reference SQL 仅通过内存 Port 夹具验证调用与异常契约，没有声称执行过真实 SQL 或 Agent。

## R1–R4 自检

- R1 PASS：比较字段/方法、行为适用范围、规则绑定、错误映射、汇总顺序和覆盖要求来自配置；
  Python 仅实现有限技术比较、类型/Schema/引用/覆盖校验及调用，不含具体指标、阈值或业务特例。
- R2 PASS：业务源码位于 domains/evaluation；纯文件 IO 位于 infrastructure/files；src 根目录无业务文件。
- R3 PASS：依赖无环；Evaluation 只通过 canonical.api / rules.api / assets.api 访问跨域 DTO 与接口。
- R4 PASS：common 未引用业务域，本阶段未创建 common。
- 其他：没有动态 import / eval / exec、SDK/ORM 实体透传、Domain → infrastructure 或逐条数据库 IO。

## 未完成项与待确认项

1. P5 确定性领域实现已完成；实际 Agent、Snapshot 和数据库 Reference Reader 接入尚未执行。
2. 默认策略和既有业务规则仍待人工批准；没有伪造生产批准、Golden 或 AI 最终裁决。
3. 冻结文档未定义 Evidence/Claim 字段级格式，本阶段的 JSON 路径、步骤上下文、覆盖声明和事实绑定契约需确认。
4. 默认类型精确比较、列表有序/无序选择与适用行为是待审核配置，不冒充已确认业务真值。
5. V5.0 在源码完成后另行接入；V4.0 已移出范围。
6. 本阶段未实现 Generation、Execution、Drift、Review、Reporting、Application 或 Presentation；P5 完成后停止。
