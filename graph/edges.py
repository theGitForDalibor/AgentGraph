"""
Jarvis Agent Pro - 静态边与拓扑连接器 (Static Edges & Pipeline Assembly)

声明静态边 (Normal Edge)、特殊虚拟节点 (START/END) 连接，
将独立的原子节点装配为确定性的线性流水线或闭环静态拓扑。
"""

from collections.abc import Sequence

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph.builder import compile_agent_graph, create_agent_graph_builder
from nodes.base import NodeFunction
from state.agent_state import AgentState


def connect_sequence(builder: StateGraph, node_sequence: Sequence[str]) -> StateGraph:
    """
    按顺序声明静态连接边 (Sequential Static Edges)

    将传入的节点序列两两以静态边连接：sequence[i] -> sequence[i+1]。
    支持包含虚拟节点 START 和 END。
    """
    if len(node_sequence) < 2:
        raise ValueError("节点序列至少需要包含 2 个节点以建立边连接")

    for i in range(len(node_sequence) - 1):
        builder.add_edge(node_sequence[i], node_sequence[i + 1])

    return builder


def build_linear_agent_graph(
    planner_node: NodeFunction,
    tool_node: NodeFunction | None = None,
) -> CompiledStateGraph:
    """
    组装标准静态执行图 (Static Linear Pipeline)

    若提供 tool_node: START -> planner -> tool_executor -> END
    若未提供 tool_node: START -> planner -> END
    """
    builder = create_agent_graph_builder(AgentState)
    builder.add_node("planner", planner_node)  # type: ignore

    if tool_node is not None:
        builder.add_node("tool_executor", tool_node)  # type: ignore
        connect_sequence(builder, [START, "planner", "tool_executor", END])
    else:
        connect_sequence(builder, [START, "planner", END])

    return compile_agent_graph(builder)


def export_mermaid_diagram(compiled_graph: CompiledStateGraph) -> str:
    """
    导出编译图的 Mermaid 流程图描述文本

    供架构审查、文档同步与拓扑连通性校验使用。
    """
    return compiled_graph.get_graph().draw_mermaid()
