# 从 Runtime Loop 到 Graph 编排迁移映射指南 (Graph Migration)

> **当前状态**: 已完成核心映射 (Phase 0~8 Implemented)  
> **迁移范式**: 过程驱动的命令式控制流 ➔ 状态驱动的声明式数据流

---

## 1. 迁移全景对照矩阵

从传统自主智能体（以自研 Jarvis Agent 命令式运行时为代表）迁移到 **AgentGraph**（声明式图编排系统），核心演进对齐如下：

| # | 命令式 Runtime Loop (自研早期实现) | AgentGraph 声明式图编排 (LangGraph) | 核心范式演进 | 当前实现状态 |
|---|---|---|---|---|
| **1** | `Runtime Loop` (`while is_running:`) | `Graph Loop` (Pregel Superstep Engine) | 命令式轮询 ➔ 声明式状态超步调度 | **Implemented** |
| **2** | `Planner` (过程式有状态调度类) | `Planner Node` (纯函数状态映射节点) | 有状态对象 ➔ 无状态纯计算原子 | **Implemented** |
| **3** | `Transition` (`if-elif-else` 内部硬编码) | `Edge` / `Conditional Edge` (解耦拓扑连线) | 硬编码跳转 ➔ 声明式解耦拓扑路由 | **Implemented** |
| **4** | `State` (内存可变字典/对象) | `Graph State` (`TypedDict` + Reducers) | 任意可变脏写 ➔ 不可变增量合并规约 | **Implemented** |
| **5** | `Approval` (同步阻塞线程 `input()`) | `Interrupt` (无状态执行挂起与恢复) | 独占式同步阻塞 ➔ 异步持久化冻结 | **Implemented** |
| **6** | `Memory` (消息追加列表/向量摘要) | `Checkpoint` (全系统时空状态快照) | 扁平文本记录 ➔ 多维时空回溯与分叉 | **Implemented** |
| **7** | `Tool Execution` (运行时内联调用) | `Tool Node` (解耦的观察者节点) | 混杂副作用 ➔ 声明式工具反馈环 | **Implemented** |
| **8** | `Sub-Agent Delegation` (子运行时递归) | `Subgraph` (嵌套图/黑盒节点) | 复杂堆栈传递 ➔ 图的嵌套组装与模式隔离 | **Implemented** |
| **9** | `Parallel Execution` (`asyncio.gather`) | `Parallel Branch` (扇出与扇入聚合) | 手工并发锁与合并 ➔ 拓扑级原生无锁确定性并发 | **Planned (Phase 10)** |
| **10**| `Context Trimming` (全局手动清理) | `State Reducers` (增量式修剪与过滤) | 易错破坏全局 ➔ 精准字段级生命周期规约 | **Partially Implemented** |

---

## 2. 核心迁移机制深度剖析

### 2.1 运行时循环：Runtime Loop ➔ Graph Loop

#### 传统命令式实现
在传统智能体中，通过显式 `while` 循环手工维护步骤计数器和状态：
```python
# 传统命令式伪代码
while not self.is_finished and self.step_count < self.max_steps:
    plan = self.planner.plan(self.state)
    if plan.requires_tool:
        observation = self.tool_executor.execute(plan.tool_call)
        self.state.append_history(plan, observation)
    else:
        self.is_finished = True
    self.step_count += 1
```
- **痛点**: 控制流与业务逻辑深度纠缠，死循环保护依赖手工计数，异常处理、中断退出需要侵入式修改循环体。

#### AgentGraph 图化实现
采用基于 Google Pregel 模型的**超步（Superstep）循环引擎**，开发者声明拓扑结构，由调度引擎接管执行：
```python
# AgentGraph 声明式实现
builder = create_agent_graph_builder(AgentState)
builder.add_node("planner", planner_node)
builder.add_node("tool_executor", tool_node)
builder.add_edge("tool_executor", "planner")
builder.add_conditional_edges(
    "planner",
    route_planner_decision,
    {ROUTER_ACTION_TOOLS: "tool_executor", ROUTER_ACTION_END: END},
)
graph = builder.compile()
graph.invoke(initial_state)
```
- **核心收益**:
  1. 控制流与业务计算彻底正交分离，主逻辑不再包含任何跳转分支。
  2. 框架内建 `recursion_limit` 熔断机制，天然杜绝死循环。
  3. 每个超步边界天然发射流式事件，支持微步级观测。

---

### 2.2 规划器：Planner ➔ Planner Node

#### 传统命令式实现
传统 `Planner` 往往是一个包含内部属性的大类，负责读取环境变量、管理提示词、调用模型并就地更新全局上下文：
- **痛点**: 内部隐式依赖私有属性，单测必须依赖复杂的运行态上下文，难以独立测试。

#### AgentGraph 图化实现
退化为严格遵循签名的**纯函数可调用对象（Callable）**：
```python
def planner_node(state: AgentState) -> dict[str, Any]:
    messages = state["messages"]
    response = model.invoke(messages)
    # 仅产出状态增量 (Delta)
    return {"messages": [response], "scratchpad": ["Planner 决策完毕"]}
```
- **核心收益**:
  1. 零副作用，输入纯字典快照，输出纯增量字典。
  2. 极高的单测友好性，可脱离图引擎进行毫秒级独立测试。

---

### 2.3 状态流转：Transition ➔ Edge & Conditional Edge

#### 传统命令式实现
在主循环内硬编码多重 `if-elif-else` 分支决定下一步操作：
- **痛点**: 业务增加一个新状态，必须重构整个调度函数，极其容易遗漏分支或引入死锁。

#### AgentGraph 图化实现
区分为**静态边（Static Edge）**与**条件边（Conditional Edge）**：
```python
# 动态条件路由函数 (Router)
def route_planner_decision(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return ROUTER_ACTION_TOOLS
    return ROUTER_ACTION_END
```
- **核心收益**:
  1. 编译期进行全图拓扑连通性校验，编译阶段即可捕获非法边或死胡同节点。
  2. 支持静态导出为 Mermaid 图，让系统架构与拓扑可视化直观审查。

---

### 2.4 状态系统：State ➔ Graph State (TypedDict + Reducers)

#### 传统命令式实现
使用共享的普通字典或 Pydantic 对象，模块各处直接进行就地可变赋值（`state["messages"].append(...)`）：
- **痛点**: 并发场景下必现写竞态与脏数据覆盖，增量更新缺乏原子性保障。

#### AgentGraph 图化实现
基于 `TypedDict` 定义结构，并绑定声明式规约器（Reducers）：
```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    scratchpad: Annotated[list[str], append_reducer]
    branch_results: Annotated[dict[str, Any], merge_dict_reducer]
    plan: dict[str, Any] | None  # 默认无 Reducer: 覆盖更新
```
- **核心收益**:
  1. 节点读取不可变快照，写入由框架在超步末期原子应用 Reducer。
  2. 天然支持消息增量幂等合并与并发分支的安全聚合。

---

### 2.5 人机协同：Approval ➔ Stateless Interrupt

#### 传统命令式实现
使用终端 `input()` 阻塞线程，或在 Web API 中长轮询挂起请求：
- **痛点**: 严重占用连接池与进程资源；服务器重启或网络抖动导致等待中的任务全量丢失。

#### AgentGraph 图化实现
基于 LangGraph 0.2 原生 `interrupt()` 触发无状态挂起与恢复：
```python
def human_approval_node(state: AgentState) -> dict[str, Any]:
    # 挂起当前超步，图引擎将状态写入 Checkpoint，进程退出
    decision = interrupt(
        {
            "question": f"核准高危操作: {state['pending_action']['name']}?",
            "action": state["pending_action"],
        }
    )
    # 外部注入 Command(resume=...) 唤醒后继续执行下一行
    if decision.get("approved"):
        return {"approval_status": "approved"}
    return {"approval_status": "rejected"}
```
- **核心收益**:
  1. 真正的无状态（Stateless）：挂起时不占用任何 CPU/线程资源。
  2. 任意时间跨度的恢复：无论是秒级终端确认还是数天后的 Web 审批，皆可准确复苏。

---

### 2.6 会话与时空：Memory ➔ Checkpoint (Time Travel)

#### 传统命令式实现
仅记录对话文本历史（Chat History），丢失了模型当时的中间推理、草稿本变量与上下文状态：
- **痛点**: 无法回退到历史任意节点排查 Bug，无法从历史状态开辟新的推演分支。

#### AgentGraph 图化实现
通过 `SqliteSaver` / `MemorySaver` 在每个超步自动提交不可变全态快照：
```python
# 追溯历史状态并开启时间旅行推演分支
config = {"configurable": {"thread_id": "session_123", "checkpoint_id": "1ef..."}}
historical_snapshot = graph.get_state(config)

# 基于历史快照更新参数并分叉执行
graph.invoke(Command(update={"messages": [HumanMessage("修改方案")]}), config)
```
- **核心收益**:
  1. 完整的系统级时空全态快照，支持步级调试与故障排查。
  2. 天然支持会话分叉（Forking）与平行推演。

---

### 2.7 计划中演进：子图与并行分支 (Phase 9 & 10)

针对尚未完成的阶段，AgentGraph 已经完成核心映射设计：
- **子图（Subgraph - Phase 9）**: 将多角色协作（Supervisor、Researcher、Coder）解耦为独立有向图，作为父图的节点调用，实现独立作用域与状态隔离。
- **并行分支（Parallel Branch - Phase 10）**: 采用扇出（Fan-out）连线实现单超步并发分发，并在扇入（Fan-in）节点通过 `merge_dict_reducer` 实现确定性聚合。
