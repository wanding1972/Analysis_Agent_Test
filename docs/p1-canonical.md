# P1 Canonical 契约与阶段记录

## 输入与范围

依据 PRD V1.1 §6、§7、§8.7、§9.3、§10、§20，以及蓝图 V0.2
§3、§5–7、§9、§14–15。只实现 Canonical，不创建其他领域的占位实现。
PRD §17 的简化目录与蓝图 §5 不一致，按用户指定的优先级采用蓝图目录。
蓝图没有定义字段级嵌套 Schema；以下结构是本阶段提出并实现的正式接口，需业务负责人确认。

## 实现计划（已执行）

1. 提取统一能力与测试语义字段，明确空值和结构约束。
2. 实现 Pydantic 模型，通过 canonical.api 公开。
3. 显式保存多步顺序和 ObjectSet 引用，不加入版本结构。
4. 测试正常及异常输入，审计生产源码依赖，检查 R1–R4。

## 正式数据契约

公开入口：`agent_test.domains.canonical.api`。外部输入使用
`Model.model_validate(payload)` 或 `Model.model_validate_json(payload)`；失败抛出
Pydantic `ValidationError`。`model_dump(mode="json")` / `model_dump_json()` 用于序列化，
`model_json_schema()` 提供 JSON Schema。核心无文件、网络或数据库 IO。

所有模型拒绝未知字段。标识字符串必须为字符串且至少含一个非空白字符，不自动修剪或改写。
所有业务标识均由调用方提供，不包含指标、操作符或版本白名单。
列表保持输入顺序；可变嵌套数据不应在验证后直接修改，修改外部数据后应重新验证完整模型。

| 模型 | 字段及约束 |
|---|---|
| CanonicalCapability | capability_id；metrics / subjects / dimensions / time_ops / filters / relations / set_ops / operations 为必填标识列表；multi_step 为严格布尔值 |
| CanonicalCapabilitySet | capabilities 为必填 Capability 列表，capability_id 唯一；允许空集合 |
| CanonicalSemanticModel | metric / grain 为必填可空标识；scope / time / operation 为必填可空嵌套模型；dimensions / filters / relations / set_operations 为必填列表 |
| CanonicalTestCase | 继承 SemanticModel；case_id / question 必填；expected_behavior 为 ANSWER、CLARIFY、REJECT Schema 枚举；step_dependencies 必填列表；steps 默认为空列表 |
| SemanticScope | subject 必填；entity_ids 默认为空列表；object_set_id 默认为 null |
| SemanticTime | operator 必填；parameters 默认为空 JSON 对象 |
| SemanticFilter | field / operator / value 必填；value 为 JSON 值，可显式 null；negated 为严格布尔值，默认 false |
| SemanticRelation | relation / source / target 为必填语义标识 |
| SetOperation | operator / result_set_id 必填；operand_set_ids 为非空标识列表，保留顺序 |
| SemanticOperation | operator 必填；parameters 默认为空 JSON 对象 |
| CanonicalStep | 继承 SemanticModel；step_id 必填且在 Case 中唯一；input_object_set_ids / output_object_set_ids 默认为空列表 |
| StepDependency | step_id 为消费步骤；depends_on 为上游步骤；object_set_id 为可空引用 |

字段未提供与显式 null 不等同；对 required nullable 字段，缺失仍然报错。
空集合、unknown、零值均原样保留，不推断业务含义。
不根据 expected_behavior 自动补齐、删除或要求某些语义字段。

`steps` 列表表示执行顺序。依赖引用必须存在，上游必须位于下游之前，从而拒绝自依赖和环。
同一依赖三元组不能重复。指定依赖 object_set_id 时，必须同时出现在生产者输出与消费者输入。
未绑定依赖的输入集合允许来自外部；模型不解析集合内容或判断查询范围是否逃逸。
操作参数是 JSON 数据，不执行其中内容。parameters 仅保存不解释，不能作为规则执行入口。

## 不属于 P1 的内容

- Metric × Scope/Grain 等兼容性、操作参数的业务约束、阈值、筛选和权重：P2 及后续领域。
- 版本映射、资产加载、AI 候选生成、Agent 调用、结果判定、Drift 和 UI。
- ObjectSet 实际成员、集合范围逃逸判定及 Agent 实际操作顺序正确性。
- Canonical 对象不代表人工批准或 Golden Truth，不授予 AI 最终裁决能力。

## 开发与验证

```sh
cd /workspace/Analysis_Agent_Test
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/unit/test_dependencies.py -q
.venv/bin/python -m pip check
```

当前依赖仅 Pydantic（数据契约）和 pytest（开发测试）。无第三方 SDK 或服务需要 Port/Adapter。
每个云任务已隔离，沿用现有 checkout，不创建 worktree。

## 待确认项

1. 嵌套模型、`steps` 补充字段及必填可空约定：冻结文档只列出顶层字段，没有给出这些细节。
2. Scope 使用 subject + entity_ids + object_set_id；具体指标与实体标识注册表由后续输入提供。
3. 时间与操作参数暂为 JSON 对象；业务参数 Schema 在获得实际语义定义后再明确，P1 不猜测。
4. 页面数量：PRD 描述四页，蓝图增加 Report；留待 P12，不影响本阶段。

## 阶段完成报告

- 完成：Canonical 模型、公开 API、Schema 校验、语义往返、多步依赖结构校验、Unit Test 与依赖审计。
- 文件：pyproject.toml、.gitignore、三个包初始化文件、canonical/models.py、canonical/api.py、
  tests/unit/canonical/test_contracts.py、tests/unit/test_dependencies.py、本文档。
- Unit Test：33 passed；包含正常与主要异常路径。
- Dependency Check：AST 检查整个生产树，TopologicalSorter 验证无环；跨域公开入口、
  Domain 不依赖 infrastructure、common 不引用业务域及允许依赖检查通过；pip check 通过。
- 依赖方向：canonical.api → canonical.models → enum / typing / pydantic。
- R1：PASS，只有结构/类型/枚举/引用校验，无业务规则，因此本阶段不创建规则配置。
- R2：PASS，业务模型只在 domains/canonical；src 根目录无平铺业务文件。
- R3：PASS，模块依赖无环。
- R4：PASS，未创建 common 包，无反向依赖。
- 未完成：P1 已实现范围无未完成项；嵌套契约待确认；P2–P12 未开始。
- 本报告只证明 Canonical 当前阶段能力，不声明应用端到端完成。完成 P1 后停止。
