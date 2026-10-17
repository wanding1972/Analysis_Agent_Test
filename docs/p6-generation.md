# P6 Generation：接口契约与阶段报告

## 依据、范围与实施计划

依据 PRD V1.1 §6、§8.2–8.7、§13、§19，以及蓝图 V0.2 §3–4、§6.3、§7–9、§14–15。
当前版本范围仍为 V4.6.1；V4.0 不需要，V5.0 延后。本阶段核心没有版本条件。

已执行：定义模板/策略/候选契约 → 约束驱动的 Pairwise 与高风险 3-wise →
Property/Metamorphic 模板及显式负例 → Claude 候选问题 Adapter → 单元/性质测试 →
既有阶段回归、依赖审计及 R1–R4 自检。不进入 P7 Execution。

## 文件清单

新增：

- `src/agent_test/domains/generation/{__init__,api,models,ports,checks,service}.py`
- `src/agent_test/infrastructure/generation/{__init__,allpairs}.py`
- `src/agent_test/infrastructure/ai/{__init__,claude_designer}.py`
- `src/agent_test/infrastructure/files/generation_config.py`
- `config/generation.yml`
- `tests/unit/generation/{conftest,test_generation,test_covering_array,test_claude_adapter}.py`
- `docs/p6-generation.md`

修改：

- `domains/rules/api.py`：公开 CompatibilityFamily / SemanticAxis 与结构投影函数。
- `domains/rules/service.py`：增加 semantic_axes 公共包装，复用已有结构投影，不复制兼容性逻辑。
- `pyproject.toml`：allpairspy 2.5.1、anthropic 1.15.0；测试依赖 Hypothesis 6.170.1。
- `.gitignore`：忽略 Hypothesis 生成的本地缓存。
- `tests/unit/test_dependencies.py`：审计新边界与 SDK 依赖。

未修改 Canonical、Assets、Version Adapter 或 Evaluation 实现；未改写任何 Golden 或正式规则。

## 公开接口

入口：`agent_test.domains.generation.api`。

```python
load_policy(source: GenerationPolicySource) -> GenerationPolicy
generate(
    request: GenerationRequest,
    combinations: CombinationDesigner,
    candidate_designer: CandidateDesigner | None = None,
) -> GenerationBatch
```

Ports：

- GenerationPolicySource.read() → 解码配置对象。
- CombinationDesigner.rows(sizes, strength, allow, max_interactions) → 整数索引行迭代器。
  allow 只接受完整行，在导出之前校验约束。
- CandidateDesigner.propose(DesignerRequest) → ProposalBatch；仅允许候选问题，不允许期望真值字段。

具体实现是 AllPairsDesigner、ClaudeCandidateDesigner、YamlGenerationPolicySource，
由调用方静态接入，不使用动态注册或动态 import。

## 正式数据契约

模型拒绝未知字段和非法 JSON/非有限数值；资源数量严格为整数。

| 契约 | 内容 |
|---|---|
| GenerationRequest | capability: CanonicalCapability、非空 seed_cases、rules: RuleSet、context: CompatibilityContext、policy；种子 ID 唯一，模板及相关 Case 引用必须存在 |
| GenerationPolicy | schema_version、approval、approved_by；Pairwise/高风险强度及高风险 capability ID 列表；候选/检查/交互预算；paraphrase_count、max_ai_candidates、ai_enabled、designer_prompt；allowed_case_types、非法组合策略/行为、generation_filters、templates |
| GenerationFilters | required_families、allow_capability_only、capability_axes、closed_world_axes、structural_operations |
| GenerationTemplate | template_id、seed_case_id、case_type、question_template、axes、rule_ids、related_seed_case_ids |
| GenerationAxis | 唯一 name、显式 targets、非空 options |
| AxisTarget | step_id；显式 null 表示根语义，否则指既有步骤 |
| AxisOption | 唯一非空 label、非空 patch；patch 只允许九个 Canonical 语义字段 |
| DesignerRequest | seeds、paraphrase_count、max_candidates、prompt |
| QuestionProposal | seed_case_id、question；不接收 expected_behavior / expected_metric / approval 等字段 |
| GeneratedTestCase | case、seed_case_id、capability_id、case_type、source、status、review_required、compatibility、rule_ids、related_seed_case_ids |
| GenerationBatch | status、candidates、rejected_counts、diagnostics、truncated、sampling、constrained_coverage_verified |

case_type 为 combination / property / metamorphic / negative / paraphrase / seed。
GeneratedTestCase.status 固定为 candidate，不能通过此模型变为正式批准状态。
AI 来源必须为 paraphrase 且 review_required=true，输出 Schema 不允许移除此标记。
Property/Metamorphic 模板必须有规则引用；Metamorphic 还必须有相关种子引用。

### 模板语义

只支持普通声明式占位符，例如 `{metric} {scope}` 与 `{question}`。
占位符必须来自声明的轴名或保留的 question；拒绝属性访问、索引表达式、转换和格式说明符。
每个轴必须出现在问题模板中，防止改变语义却完全不改变问题。
不同轴不能覆盖同一语义槽位，选项标签不能重复；不猜测优先级或深层合并规则。

patch 应提供完整字段值。需要根与步骤同步变化时，在 targets 中显式列出二者。
步骤 ID、输入/输出 ObjectSet 和依赖不被自动重写。生成后重新通过 Canonical Schema 校验。
多指标/scopes 等 P4 中性参数若存在，必须与顶层别名一致；不一致的候选被阻塞。
比较操作数中的 Canonical 语义也进入约束检查，不能藏入未声明指标。

业务问题含义由配置所有者负责。引擎不以 NLP/AI 推断模板文字是否足以表达期望语义，
更不会自动将生成后的期望值设为 Golden。

## 约束、负例及规则派生

capability_axes 将 Canonical 语义轴映射到 CanonicalCapability 声明字段，值来自配置。
缺少能力元数据不被当作“业务已证实不支持”：默认 closed_world_axes 为空，未知值阻塞。
只有显式封闭世界配置或正式兼容规则可以给出已知非法组合。
默认结构性 sequence 不作为业务操作轴判断，其各步骤仍分别检查。

Compatibility 使用 Rules 公共接口。每个根/步骤/比较操作数都须满足配置的 required_families：
没有规则、全部不适用或未批准不能作为兼容证明。
required_families 为空也不能自动放行，除非配置明确允许 capability-only 模式。
默认配置要求八类兼容检查，并禁止这种隐式放行。

非法组合策略为配置中的 exclude 或 negative；negative 的期望行为同样来自配置。
未知/缺失知识和 Schema 错误永远不自动变成负例，避免把不完整声明当成 REJECT 真值。
负例还须在 allowed_case_types 中显式允许。

Property/Metamorphic 模板保留正式 rule_ids 与 related_seed_case_ids；未批准或类别不匹配时阻塞。
边界值通过轴选项明确列出，不从源码中猜阈值。生成阶段不读取数据、不执行规则的数值判定；
实际 Property/Metamorphic 判断留给已实现的 Evaluation，相关执行须使用同 Snapshot。

## 采样、预算和覆盖证据

- Pairwise 使用 allpairspy，通过 Adapter 接收完整行约束回调。
- 实测 allpairspy 的 n=3 在 3 个二值轴上只生成 4 行，缺失应有的三元交互，不能直接宣称完整 3-wise。
- Adapter 因此先生成 Pairwise 行，再枚举三轴局部交互，对尚未出现的交互寻找满足约束的完整见证行。
  不对所有维度做无界全排列；三个轴的三元交互本身需要覆盖全部八个三元值，这是 3-wise 的定义。
- 独立 Hypothesis 测试投影二元/三元交互，与局部数学全集比较，验证小型无约束矩阵覆盖；
  另有明确的上游 n=3 缺口回归测试。
- 任意约束下，启发式未找到见证不能证明不可满足。后端结束也不证明已覆盖所有合法交互，
  constrained_coverage_verified 固定为 false，不伪造形式化覆盖证明。

max_generated_cases 是整批输出上限；max_candidate_checks 是整批新候选检查上限；
max_interaction_checks 限制每个模板的三元交互枚举。到限保留已有候选并报告 truncated/partial。
sampling 记录请求/有效强度、后端是否自然结束和导出行数，不能替代独立覆盖证据。
GenerationBatch.ready 只表示本批候选采样没有报告阻塞/截断，不代表候选已批准或业务测试通过。

候选 ID 由规范化语义、问题、类型和关联信息确定性生成；重复候选去重并计数。
相同候选不会因为采样顺序而换 ID。缺少知识、配额不足与真正被规则排除的行分别记录。

## Claude 边界

ClaudeCandidateDesigner 使用官方 Anthropic SDK，强制返回指定 tool 的 ProposalBatch。
拒绝截断响应、错误/多个 tool、超额候选及额外真值字段；不保存自由文本推理内容。
Domain 还检查种子引用和每种子数量；只替换问题文字，期望语义与行为来自原种子。
所有 AI 问题保留候选/需复核标记，不能把模型的同义改写当成已经验证的语义等价。

同一批种子仅发送一次设计请求，不逐条调用 AI。达到候选上限后不调用 AI。
SDK/IO 异常在 Adapter 转换为 CandidateDesignError 并记录稳定日志，不记录原始响应和凭据。
失败时保留确定性候选并返回 partial；重复问题导致唯一候选不足时也明确报告配额未满足。

调用方必须显式提供 Anthropic client 和 ClaudeDesignerSettings：实际 model_id、max_tokens、timeout_seconds。
代码没有模型/密钥假默认值，没有关闭 TLS 或修改认证配置。
本轮仅检查 ANTHROPIC_API_KEY / CLAUDE_API_KEY 是否存在（未读取/打印值），未检测到指定变量；
官方 SDK 的请求/响应通过离线 MockTransport 验证，没有真实网络请求或真实模型验证。
实际启用时应通过环境设置配置凭据，不在聊天或仓库中填写。

## 验证与阶段报告

```sh
cd /workspace/Analysis_Agent_Test
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q -W error
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q -s
.venv/bin/python -m pip check
```

- 379 passed：本阶段新增 59 项，P1–P5 回归 320 项；无失败、跳过、预期失败或测试警告。
- 包含 Hypothesis 性质测试、实际 SDK 离线协议、两种采样强度、约束/负例、三类预算、
  缺失/未批准规则、模板注入、步骤/ObjectSet 保留、AI 过量/无效响应、来源标记及确定性去重。
- 40 组明确标记的合成种子生成 320 条唯一候选，仅证明算法规模处理，不是 300 条真实业务有效 Case 验收。
- 52 个生产模块 DAG 与领域边界审计通过，可编辑安装及 pip check 通过。

## R1–R4 自检

- R1 PASS：强度、上限、轴值、模板、风险名单、能力筛选、兼容要求及负例行为均来自配置/Canonical 输入。
  Python 仅实现有限采样算法、配置解释、类型/Schema/引用校验和异常处理，无具体业务阈值或指标特例。
- R2 PASS：业务源码位于 domains/generation；SDK 位于 infrastructure；src 根目录无业务文件。
- R3 PASS：52 模块无环；跨域只使用 canonical.api / rules.api，不依赖 Versioning、Execution 或 Evaluation。
- R4 PASS：common 无业务引用，本阶段未创建 common。

## 未完成项、限制与待确认项

1. P6 本阶段代码和检查已完成；默认生成策略为 proposed，正式兼容表为空且 templates 未填。
   真实生产生成仍需经确认的 Canonical 种子、与矩阵一致的能力/Context、模板和正式兼容规则。
2. V4.6.1 的能力投影包含不完整声明限制，不能将未知 filters / time_ops 等补成支持或不支持。
3. 实时 Claude 调用未验证；本阶段 AI 范围为基于种子的候选同义问法，不把 AI 期望语义/规则建议当作正式真值。
   非法组合和边界/Property/Metamorphic 候选由明确配置生成。
4. 轴 patch/target 契约、负例策略、封闭世界轴和配额配置是本阶段补充的字段级接口，需确认。
5. 不宣称任意约束下完整 t-wise 覆盖；不以合成夹具替代真实业务 Case 验收。
6. 未生成正式业务资产，未批准规则/Golden，未实现 P7–P12。P6 完成后停止，等待进入 P7。
