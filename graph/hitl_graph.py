"""
Jarvis Agent Pro - 人机协同图装配器 (HITL Graph Builder)

装配支持高危操作人工审查、无状态中断 (Interrupt) 与指令恢复 (Resume) 的状态图：
START -> Planner -(有敏感工具)-> Human Approval -(中断挂起 / Resume)-
                  │                                  ├─(通过)─> Tool Executor ──┐
                  ├─(普通工具)───────────────────────┘                         │ (反馈)
                  └─(最终回答)─> END                                          ▼
                                 ▲                                          Planner
                                 └───────────────(驳回回环)────────────────────┘
"""

from collections.abc import Sequence
from typing import Final, Literal

from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph

from graph.builder import compile_agent_graph, create_agent_graph_builder
from nodes.base import NodeFunction
from nodes.human_approval import DEFAULT_SENSITIVE_TOOLS, create_human_approval_node
from state.agent_state import AgentState

ROUTER_HITL_APPROVAL: Final = "human_approval"
ROUTER_HITL_TOOLS: Final = "tool_executor"
ROUTER_HITL_PLANNER: Final = "planner"
ROUTER_HITL_END: Final = "end"


def build_hitl_agent_graph(
    planner_node: NodeFunction,
    tool_node: NodeFunction,
    sensitive_tools: Sequence[str] | frozenset[str] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装支持人机协同 (HITL) 中断恢复的完整状态图

    Args:
        planner_node: 规划与决策节点
        tool_node: 工具调度与执行节点
        sensitive_tools: 需要人工审批的高危工具名称清单
        checkpointer: 检查点持久化存储 (若为空则默认使用 MemorySaver)

    Returns:
        CompiledStateGraph: 支持 interrupt/resume 的编译后执行图
    """
    protected_tools = frozenset(sensitive_tools) if sensitive_tools else DEFAULT_SENSITIVE_TOOLS
    approval_node = create_human_approval_node(sensitive_tools=protected_tools)
    active_checkpointer = checkpointer or MemorySaver()

    builder = create_agent_graph_builder(AgentState)

    # 1. 注册核心节点
    builder.add_node("planner", planner_node)  # type: ignore
    builder.add_node("human_approval", approval_node)  # type: ignore
    builder.add_node("tool_executor", tool_node)  # type: ignore

    # 2. 入口连线: START -> planner
    builder.add_edge(START, "planner")

    # 3. Planner 条件分支：判断结束、进入审批或直接执行工具
    def route_after_planner(
        state: AgentState,
    ) -> Literal["human_approval", "tool_executor", "end"]:
        messages = state.get("messages", [])
        if not messages:
            return ROUTER_HITL_END

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage):
            return ROUTER_HITL_END

        tool_calls = getattr(last_message, "tool_calls", None) or []
        if not tool_calls:
            return ROUTER_HITL_END

        if any(tc.get("name") in protected_tools for tc in tool_calls):
            return ROUTER_HITL_APPROVAL

        return ROUTER_HITL_TOOLS

    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            ROUTER_HITL_APPROVAL: "human_approval",
            ROUTER_HITL_TOOLS: "tool_executor",
            ROUTER_HITL_END: END,
        },
    )

    # 4. Human Approval 条件分支：通过则执行工具，驳回则将拒绝消息回环至 planner
    def route_after_approval(
        state: AgentState,
    ) -> Literal["tool_executor", "planner"]:
        if state.get("approval_status") == "approved":
            return ROUTER_HITL_TOOLS
        return ROUTER_HITL_PLANNER

    builder.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            ROUTER_HITL_TOOLS: "tool_executor",
            ROUTER_HITL_PLANNER: "planner",
        },
    )

    # 5. 工具执行完毕后回环至 Planner
    builder.add_edge("tool_executor", "planner")

    return compile_agent_graph(builder=builder, checkpointer=active_checkpointer)
