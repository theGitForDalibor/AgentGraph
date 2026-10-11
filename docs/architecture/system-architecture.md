# AgentGraph 系统架构设计 (System Architecture)

> **当前状态**: 已实现 (Implemented - Phase 0~10 全部完成 + CLI Application Layer)  
> **核心机制**: 基于 LangGraph 的声明式有向状态图、Pregel 超步执行引擎、分层子图与并发分支

---

## 1. 架构定位与设计哲学

AgentGraph 是自主智能体从**命令式运行时循环（Imperative Runtime Loop）**向**声明式图编排系统（Declarative Graph Orchestrator）**演进的工业级参考工程实现。

传统的自主智能体往往依赖一个过程式的 `while` 循环驱动全局逻辑。随着智能体业务复杂度攀升，这种命令式架构暴露出控制流面条化、并发状态竞态、人机协同（HITL）阻塞等待、缺乏细粒度时空状态快照、多角色子图耦合以及并发无法确定性规约等系统级缺陷。

AgentGraph 采用严格的分层解耦架构，将智能体的“思考、决策、工具调用、人工介入、持久化、多智能体协同、并发审查”全部抽象为**图拓扑（Graph Topology）**与**状态规约（State Reducer）**，从上层应用接口到底层持久化存储，层层确立清晰的工程边界与类型契约。

---

## 2. 分层架构与图编排拓扑 (Architecture Topology)

### 2.1 系统全局拓扑图 (含分层子图与并发分支)

```mermaid
flowchart TD
    %% 1. 应用接入层
    subgraph AppLayer["1. 终端应用层 (Application Layer)"]
        CLI["CLI 终端命令行客户端 (Typer / Rich UI)<br><code>chat</code> | <code>run</code> | <code>supervise</code> | <code>review</code>"]
    end

    %% 2. 图编排引擎层 (三大运行拓扑)
    subgraph EngineLayer["2. 声明式图编排引擎层 (StateGraph Engine)"]
        direction TB

        subgraph ReActFlow["模式 A: 基础 ReAct & HITL 闭环 (Phase 1~8)"]
            direction LR
            P["Planner 规划节点"] -->|决策工具| R_Check{敏感操作?}
            R_Check -->|普通操作| T["Tool 执行节点"]
            R_Check -->|高危拦截| H["Human Approval (无状态挂起)"]
            T -->|工具反馈回环| P
            H -.->|Command 唤醒| T
        end

        subgraph HierarchicalFlow["模式 B: 分层多智能体协同 (Phase 9: Supervisor + Subgraphs)"]
            direction LR
            Sup["Supervisor 主管"] -->|1. 派发调研| SubR
            SubR -.->|2. 交付简报| Sup
            Sup -->|3. 需求下发| SubC
            SubC -.->|4. 交付代码| Sup
            Sup --> Syn["成果汇总 Synthesizer"]

            subgraph SubR["Researcher 调研子图 (独立私有 ResearcherState)"]
                direction TB
                RP["research_planner 检索规划"] <--> SE["search_executor 知识检索"]
            end

            subgraph SubC["Coder 研发子图 (独立私有 CoderState)"]
                direction TB
                CD["coder_draft 代码起草"] --> CT{"coder_test 语法自测"}
                CT -->|未通过自测| CD
            end
        end

        subgraph ParallelFlow["模式 C: 扇出扇入并发审查 (Phase 10: Fan-Out / Fan-In)"]
            direction LR
            Disp["Dispatcher 任务分发"]
            Disp ==> Sec["安全漏洞审计节点"]
            Disp ==> Perf["性能复杂度分析节点"]
            Disp ==> Style["PEP8 编码规范节点"]
            Sec & Perf & Style ==> Agg["加权决议汇聚 Aggregator"]
        end
    end

    %% 3. 状态与存储底座
    subgraph StateLayer["3. 状态管理与持久化底座 (State & Storage)"]
        direction LR
        State["AgentState 单一可信数据源<br>(add_messages / append_reducer / merge_dict_reducer)"]
        CP["SqliteSaver 状态检查点持久化<br>(全系统时空快照 / 多会话隔离 / 时间旅行)"]
    end

    %% 4. 执行与适配基础设施
    subgraph InfraLayer["4. 基础设施与外部环境 (Infrastructure & Environment)"]
        direction LR
        LLM["LLM Adapter 模型统一适配<br>(离线确定性 DemoModel / 通用 OpenAI 兼容协议)"]
        Tools["本地工具执行与安全拦截<br>(计算器 / 系统探测 / 文件读取 / 敏感工具注册表)"]
    end

    %% 层间流转关系
    CLI -->|初始化与模式选择| EngineLayer
    EngineLayer <-->|不可变快照读取 / 原子规约提交| StateLayer
    EngineLayer -.->|模型推理| LLM
    EngineLayer -.->|工具调用| Tools
```

### 2.2 模块分层职责清单

| 架构层级 | 源码目录 | 核心职责 | 当前实现状态 |
| :--- | :--- | :--- | :--- |
| **Application Layer** | `cli/` | 提供终端交互入口（Typer/Rich），包含 `chat`, `run`, `supervise`, `review`, `sessions` 子命令，支持多引擎模式切换。 | **Implemented** |
| **StateGraph Layer** | `graph/` | 维护有向图拓扑，包含图构建器、条件路由、ReAct 图、HITL 图、分层 Supervisor 主图（`parent_graph.py`）、并发分支图（`parallel_graph.py`）及领域独立子图（`subgraphs/`）。 | **Implemented** |
| **Nodes Layer** | `nodes/` | 无状态纯函数/可调用对象节点。包含规划器（`planner.py`）、工具执行器（`tool_executor.py`）、人工审批（`human_approval.py`）、并发汇聚（`aggregators.py`）及异常边界装饰器（`base.py`）。 | **Implemented** |
| **State Layer** | `state/` | 强类型数据模型（`agent_state.py`）。定义统一状态模式及 `add_messages`、`append_reducer`、`merge_dict_reducer` 规约器。 | **Implemented** |
| **Tools Layer** | `tools/`, `cli/tools.py` | 封装智能体与物理环境交互的具体能力（计算器、系统信息采集、文件读取、模拟删除等）及高危工具拦截注册表。 | **Implemented** |
| **LLM Adapter Layer** | `cli/llm_factory.py` | 大语言模型统一适配层。提供离线确定性 Demo 规则桩（`DemoModel`）与通用 OpenAI 兼容协议客户端（`OpenAICompatibleModel`）。 | **Implemented** |
| **Infrastructure Layer** | `checkpoints/` | 状态持久化与快照管理。提供 `create_sqlite_saver`、`create_memory_saver` 及时间旅行管理器 `CheckpointManager`。 | **Implemented** |

---

## 3. 典型端到端执行时序 (Execution Sequence)

以下展示一次包含**大模型意图规划 ➔ 敏感操作拦截 ➔ 人工核准 ➔ 工具执行 ➔ 结果反馈**的完整端到端生命周期：

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户 (User)
    participant App as Application Layer (CLI)
    participant SG as StateGraph Engine
    participant State as State (Single Source of Truth)
    participant Planner as Planner Node
    participant Approval as Human Approval Node
    participant Tool as Tool Executor Node
    participant CP as Checkpointer (Sqlite)

    User->>App: 发送任务指令 ("帮我清理 app.log")
    App->>State: 初始化 AgentState (thread_id="session_01", messages=[HumanMessage])
    App->>SG: graph.invoke(initial_state, config)

    Note over SG,CP: 【超步 1: 规划决策】
    SG->>Planner: 触发执行 planner(state)
    Planner-->>SG: 返回增量 {"messages": [AIMessage(tool_calls=[danger_delete_file])]}
    SG->>State: add_messages 规约合并增量
    SG->>CP: 持久化当前 Step 1 快照

    Note over SG,Approval: 【条件边路由: 命中敏感工具列表】
    SG->>Approval: 触发执行 human_approval(state)
    Approval-->>SG: 抛出 GraphInterrupt (无状态冻结挂起)
    SG->>CP: 写入挂起状态检查点
    SG-->>App: 返回中断信号与审查上下文 (Payload)

    Note over App,User: 【人机交互审查】
    App->>User: 终端提示: "检测到敏感操作 danger_delete_file，是否核准？[y/N]"
    User->>App: 确认核准 ("y")

    Note over App,SG: 【恢复执行 (Resume)】
    App->>SG: graph.invoke(Command(resume={"approved": True}), config)
    SG->>CP: 读取 Step 1 挂起检查点唤醒
    Approval-->>SG: 返回审批核准状态增量
    SG->>CP: 持久化 Step 2 快照

    Note over SG,Tool: 【超步 3: 工具执行】
    SG->>Tool: 触发执行 tool_executor(state)
    Tool-->>SG: 返回增量 {"messages": [ToolMessage(observation)]}
    SG->>State: add_messages 规约合并观察
    SG->>CP: 持久化 Step 3 快照

    Note over SG,Planner: 【超步 4: 结果总结】
    SG->>Planner: 静态回环触发 planner(state)
    Planner-->>SG: 返回最终回答 {"messages": [AIMessage("任务已顺利完成")]}
    SG->>State: 合并最终回复
    SG->>CP: 持久化 Step 4 快照

    Note over SG,App: 【条件路由: 判定结束流向 END】
    SG-->>App: 交付最终 State
    App-->>User: 呈现执行结论与结构化输出
```

---

## 4. Pregel 超步调度与生命周期 (Superstep Engine Lifecycle)

LangGraph 并非简单的顺序脚本，其内部由基于 Google Pregel 分布式图模型的**超步迭代机（Superstep Engine）**调度。

```mermaid
stateDiagram-v2
    [*] --> GraphDefinition: 1. 图拓扑定义 (add_node / add_edge)
    GraphDefinition --> GraphCompilation: 2. 静态编译与连通性校验 (compile)
    GraphCompilation --> StateInitialization: 3. 输入载荷接入与 Checkpoint 恢复
    
    state "Pregel Superstep 调度循环" as SuperstepLoop {
        StateInitialization --> SnapshotFreeze: 4. 生成当前超步不可变只读快照
        SnapshotFreeze --> ConcurrentDispatch: 5. 调度并发执行所有入度激活节点
        ConcurrentDispatch --> ReducerApply: 6. 收集增量字典 (Deltas) 并执行 Reducers
        ReducerApply --> CommitCheckpoint: 7. 提交新状态并生成唯一递增 Checkpoint
        CommitCheckpoint --> RoutingEvaluation: 8. 条件边评估与中断规则判定
        RoutingEvaluation --> SnapshotFreeze: 存在下一待执行节点集合
    }

    RoutingEvaluation --> StatelessInterrupt: 命中中断 (HITL interrupt)
    StatelessInterrupt --> SnapshotFreeze: 外部注入 Command(resume=...) 唤醒

    RoutingEvaluation --> Termination: 所有活跃分支流向 END 节点
    Termination --> [*]
```

### 4.1 超步执行各阶段深度说明

1. **图拓扑定义 (Definition)**:
   - 实例化 `builder = StateGraph(AgentState)`。
   - 注册原子计算节点：`builder.add_node("planner", planner_node)`。
   - 声明起始入口（`START`）、终止出口（`END`）、静态边（`add_edge`）与动态条件边（`add_conditional_edges`）。
2. **静态编译校验 (Compilation)**:
   - 触发 `compiled_graph = builder.compile(checkpointer=..., interrupt_before=...)`。
   - 静态校验拓扑完整性：若存在悬空边（Dangling Edge）或未注册的幽灵节点，编译期立即抛出 `ValueError`。
3. **输入载荷与检查点恢复 (Invocation & Recovery)**:
   - 接收用户输入与 `RunnableConfig(configurable={"thread_id": "..."})`。
   - 若数据库存在该 `thread_id` 的历史检查点，框架自底向上恢复最新状态快照；若不存在，则根据 `AgentState` 规范初始化新状态。
4. **只读快照生成 (Frozen Snapshot)**:
   - 每个超步开始时，系统创建当前状态的冻结视图。同一超步内并发调度的多个节点只能读取该完全一致的快照，严禁就地修改。
5. **节点并发分发 (Node Execution)**:
   - 调度器异步并发执行当前激活的节点。节点内部包含异常隔离边界（`with_error_boundary`），确保单个工具崩溃不会导致进程崩溃。
6. **状态规约与增量合并 (Reducer Application)**:
   - 节点仅产出部分字段的差量更新（Delta）。
   - 框架统一遍历差量，交由字段预先绑定的规约器（如 `add_messages`、`append_reducer`）执行原子合并。
7. **检查点提交 (Checkpoint Commit)**:
   - 框架将当前超步规约后的完整状态、Step 计数器、父检查点 ID 写入持久化存储（SQLite），产生不可变时空快照。
8. **边评估与无状态中断 (Routing & Interrupt)**:
   - 执行条件路由函数计算下游节点。
   - 若节点内部触发 `interrupt()`，图引擎立即抛出 `GraphInterrupt` 控制信号，安全挂起执行并持久化上下文，完全释放线程与连接。
9. **图终止 (Termination)**:
   - 当条件边指向 `END` 常量且活动执行队列为空时，图生命周期正常终止，交付最终结果。

---

## 5. 核心工程边界与设计约束

1. **节点纯函数约束 (Pure Functions)**:
   - 节点严禁持有内部可变实例变量。
   - 输入为不可变状态快照，输出必须为字典类型增量更新（`dict[str, Any]`）。
2. **控制流与业务分离**:
   - 节点只负责生产数据，严禁在节点代码内硬编码跳转逻辑。
   - 所有分支流转必须显式交给 `add_conditional_edges` 中的路由函数处理。
3. **异常隔离与控制流放行**:
   - 业务异常必须在节点内部被 `with_error_boundary` 捕获并降级为观察消息。
   - 框架级控制流信号（如 `GraphInterrupt`、`GraphRecursionError`）严禁被普通 `except Exception:` 吞没，必须向上传播给图引擎调度器。
