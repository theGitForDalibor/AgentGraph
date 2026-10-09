"""
Jarvis Agent Pro - ReAct 闭环图装配器 (ReAct Loop Graph Builder)

装配完整的 ReAct 决策反馈拓扑：
START -> Planner -(条件边: 有工具)-> Tool Executor -(反馈边)-> Planner
                 -(条件边: 最终回复)-> END
"""

from collections.abc import Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph

from graph.builder import compile_agent_graph, create_agent_graph_builder
from graph.router import (
    ROUTER_ACTION_END,
    ROUTER_ACTION_TOOLS,
    route_planner_decision,
)
from nodes.base import NodeFunction
from state.agent_state import AgentState


def build_react_agent_graph(
    planner_node: NodeFunction,
    tool_node: NodeFunction,
    checkpointer: BaseCheckpointSaver | None = None,
    interrupt_before: Sequence[str] | None = None,
    interrupt_after: Sequence[str] | None = None,
) -> CompiledStateGraph:
    """
    组装完整的 ReAct 自适应闭环状态图

    Args:
        planner_node: 规划与决策节点
        tool_node: 工具调度与执行节点
        checkpointer: 可选的检查点持久化存储
        interrupt_before: 节点前中断列表 (HITL)
        interrupt_after: 节点后中断列表 (HITL)

    Returns:
        CompiledStateGraph: 可执行的 ReAct 闭环图
    """
    builder = create_agent_graph_builder(AgentState)

    # 1. 注册原子节点
    builder.add_node("planner", planner_node)  # type: ignore
    builder.add_node("tool_executor", tool_node)  # type: ignore

    # 2. 初始入口连线: START -> planner
    builder.add_edge(START, "planner")

    # 3. 动态条件边: planner 根据输出决策分发
    builder.add_conditional_edges(
        "planner",
        route_planner_decision,
        {
            ROUTER_ACTION_TOOLS: "tool_executor",
            ROUTER_ACTION_END: END,
        },
    )

    # 4. 观测反馈回环: tool_executor -> planner
    builder.add_edge("tool_executor", "planner")

    return compile_agent_graph(
        builder=builder,
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )
