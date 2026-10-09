# 检查点持久化与时间旅行机制 (Checkpoint & Time Travel)

> **当前状态**: 已实现 (Implemented - Phase 8)  
> **核心组件**: `checkpoints/manager.py`, `graph/checkpointed_graph.py`

---

## 1. 为什么 Checkpoint 远胜于普通 Memory

在常规的智能体实现中，“记忆（Memory）”通常指将对话文本保存在数据库或向量库中：
- **普通 Memory 的局限**: 仅能还原“说了什么话”，无法恢复智能体的“思考状态、临时草稿、正在等待的工具调用 ID、当前超步进度”。
- **AgentGraph Checkpointer 的突破**: 在每个**超步（Superstep）**结束时对整个状态图的完整系统状态进行原子持久化快照。

```
普通 Memory:      [User: "查天气"] ──> [AI: "北京晴"] (仅保留对话文本)

AgentGraph:       Step 1 (Planner Snapshot) ──> Step 2 (Tool Exec Snapshot) ──> Step 3 (Final Snapshot)
                  包含: messages, plan, pending_action, scratchpad, metadata, thread_id, checkpoint_id
```

---

## 2. 检查点架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                       StateGraph Engine                     │
└──────────────────────────────┬──────────────────────────────┘
                               │ 每个 Superstep 自动触发写入
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     CheckpointManager                       │
│    (Session Isolation / State History / Time Travel Fork)   │
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│        SqliteSaver          │ │         MemorySaver         │
│ (.jarvis_checkpoints.db)    │ │   (Transient Unit Tests)    │
└─────────────────────────────┘ └─────────────────────────────┘
```

### 2.1 核心工厂与管理器 API
源码位置: `checkpoints/manager.py`

- `create_memory_saver() -> MemorySaver`: 创建轻量级纯内存检查点存储，常用于无外部 IO 依赖的高速单元测试。
- `create_sqlite_saver(db_path: str = ".jarvis_checkpoints.db") -> SqliteSaver`: 创建基于本地 SQLite 的磁盘持久化存储。
- `compile_with_checkpointer(builder, checkpointer) -> CompiledStateGraph`: 将检查点拦截器原子注入状态图编译流程。
- `CheckpointManager(compiled_graph)`: 高阶管理器，提供历史检查点反查、会话追溯与时间旅行支持。

---

## 3. SQLite 持久化表结构与数据模型

在使用 `SqliteSaver` 时，数据库底层自动维护状态版本树：

| 字段名称 | 类型 | 说明 |
| :--- | :--- | :--- |
| `thread_id` | TEXT | 会话唯一隔离标识符，多用户/多会话互不干扰。 |
| `checkpoint_id` | TEXT | 单调递增的快照 ID，代表一个确定的执行超步。 |
| `parent_checkpoint_id` | TEXT | 上一超步的快照 ID，形成可追溯的 DAG 版本树。 |
| `checkpoint` | BLOB | 经由框架序列化的完整 `AgentState` 对象（包含全部消息对象与字段）。 |
| `metadata` | BLOB | 该步产生的元信息（触发节点名称、Step 序号、写操作记录）。 |

---

## 4. 多会话隔离 (Session Isolation)

AgentGraph 通过 `RunnableConfig` 中的 `thread_id` 实现严格的状态隔离：

```python
# 会话 A (用户 1)
config_a = {"configurable": {"thread_id": "session_user_001"}}
graph.invoke({"messages": [HumanMessage("我的名字是 Alice")]}, config_a)

# 会话 B (用户 2)
config_b = {"configurable": {"thread_id": "session_user_002"}}
graph.invoke({"messages": [HumanMessage("我的名字是 Bob")]}, config_b)

# 查询验证：会话 A 无法感知会话 B 的存在，完全物理隔离
state_a = graph.get_state(config_a)
assert "Alice" in str(state_a.values["messages"])
```

---

## 5. 时间旅行机制 (Time Travel & Forking)

时间旅行是 AgentGraph 最具工程价值的能力之一，用于：
1. **故障回溯与调试**: 当智能体在 Step 5 发生意图偏离或工具报错时，开发者可以直接拉取 Step 4 的快照，修改 Prompt 或输入参数重新推演。
2. **假设分析（What-If Analysis）**: 从历史某一关键决策点开辟平行分支，对比不同决策路径的产出效果。

### 5.1 获取历史检查点列表
```python
manager = CheckpointManager(compiled_graph)

# 获取当前会话所有的历史执行超步快照
history_list = manager.get_history(thread_id="session_123")
for record in history_list:
    step_id = record.config["configurable"]["checkpoint_id"]
    print(f"Step ID: {step_id}, Nodes: {record.next}")
```

### 5.2 历史分叉推演 (Forking)
```python
# 1. 选定历史上的某一个检查点 ID (如 step_2_id)
target_step_id = history_list[2].config["configurable"]["checkpoint_id"]

# 2. 构造分叉配置
fork_config = manager.build_time_travel_config(
    thread_id="session_123",
    checkpoint_id=target_step_id,
)

# 3. 基于历史快照更新参数并执行分叉分支
from langgraph.types import Command

fork_result = compiled_graph.invoke(
    Command(update={"messages": [HumanMessage("修正后的新问题")]}),
    config=fork_config,
)
```
- **核心保障**: 分叉推演会派生出新的子检查点，**绝对不会篡改或破坏主线原有的历史记录**。
