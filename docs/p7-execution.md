# P7 Execution：Agent 执行与 MCP Adapter

## 范围

P7 将 Canonical Test Case 通过 Agent 执行端口发送到目标 Agent，并保存可供后续 Evaluation 使用的稳定观察结果。本阶段不判定答案正确性、不执行 Drift/Review/Reporting，也不宣称真实 Agent 已接通。

目标 MCP 依据用户提供的 `verify_mcp.py`：

1. `initialize` 握手，协议版本默认 `2025-03-26`；
2. 从响应头保存 `Mcp-Session-Id`；
3. 调用 `tools/call` 的 `ask` 工具，参数为 `{ "question": ... }`；
4. 解析 `application/json` 或 `text/event-stream`；
5. 将目标 Agent 的 `answered`、`clarify`、`blocked`、`error` 转成稳定 Observation。

## 公开接口

领域入口：`agent_test.domains.execution.api`。

```python
execute(request: ExecutionRequest, executor: AgentExecutor) -> ExecutionBatch
```

基础设施 Adapter：`agent_test.infrastructure.mcp.vida.VidaMcpExecutor`。

```python
VidaMcpExecutor(VidaMcpSettings(url="http://.../mcp"))
```

`ExecutionRequest` 以 `run_id`、Canonical Test Cases、批量上限和超时组成。每条 Observation 使用稳定的 `{run_id}:{case_id}` 作为 `snapshot_id`，保留问题、状态、回答和稳定错误码。

## 边界与错误

- Domain 只依赖 `canonical.api` 与 Execution 自身；不依赖 MCP 或其他 infrastructure。
- Adapter 不记录响应正文、凭据或原始异常；传输、SSE、JSON-RPC 和返回 Schema 错误统一转换为 `ExecutionError`。
- 超出批量上限时在任何 IO 之前返回 `blocked/case_limit_exceeded`。
- 单条失败不吞掉整批；已有 Observation 保留，批次标为 `partial`。
- P7 不将 Agent 的 `answered` 视为业务正确，也不生成 Golden 或批准状态。

## 验证

- P7 离线单元测试覆盖：正常答复、澄清、SSE/纯 JSON 解析、非法 SSE、传输失败、批量上限和稳定 Snapshot ID。
- 使用用户提供的真实 MCP URL 仍需显式执行联调；当前环境没有将远程调用结果当作验收证据。
