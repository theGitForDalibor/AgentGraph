"""
Jarvis Agent Pro - 调研子图 (Researcher Subgraph)

专职负责特定主题的知识与信息深度检索。
拥有独立于父图的私有状态空间 (ResearcherState) 与内部 ReAct 推理闭环，
对父图提供黑盒化的调研报告输出，避免子图高频检索污染父图上下文。
"""

from collections.abc import Callable, Sequence
from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from graph.builder import compile_agent_graph, create_agent_graph_builder
from state.agent_state import append_reducer


class ResearcherState(TypedDict):
    """
    Researcher 子图专属私有状态模型 (黑盒作用域)
    """

    # 1. 调研核心主题
    topic: str

    # 2. 搜索查询历史记录 (使用 append_reducer 累加)
    queries: Annotated[list[str], append_reducer]

    # 3. 收集到的原始资料与文档片段 (使用 append_reducer 累加)
    documents: Annotated[list[str], append_reducer]

    # 4. 子图内部思考消息序列
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # 5. 提炼出的最终结构化调研报告
    summary: str | None


def default_search_tool(query: str) -> str:
    """默认离线/模拟资料检索工具"""
    query_lower = query.lower()
    if "agent" in query_lower or "graph" in query_lower:
        return "LangGraph 基于 Pregel 超步引擎，采用状态图建模智能体有向闭环与多智能体拓扑。"
    if "python" in query_lower:
        return "Python 3.12+ 提供了更优秀的类型注解支持与泛型语法 (PEP 695)。"
    return f"关于 '{query}' 的深度调研资料：已完成多维事实搜集与交叉比对。"


def build_researcher_subgraph(
    model: Any | None = None,
    search_tool: Callable[[str], str] | None = None,
    max_search_steps: int = 2,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装并编译专职调研子图 (Researcher Subgraph)

    Args:
        model: 模型调用适配器，若为 None 则使用内建规则模型
        search_tool: 资料检索工具函数
        max_search_steps: 最大检索轮次，防止无限搜索
        checkpointer: 可选的子图专属检查点存储器

    Returns:
        CompiledStateGraph: 编译就绪的独立调研子图
    """
    active_search = search_tool or default_search_tool
    builder = create_agent_graph_builder(ResearcherState)

    def planner_node(state: ResearcherState) -> dict[str, Any]:
        """子图规划节点：评估现有资料，决定继续搜索或生成报告"""
        docs = state.get("documents", [])
        queries = state.get("queries", [])
        topic = state.get("topic", "未命名主题")

        # 若达到最大检索轮次或已获取资料，则提炼报告
        if len(queries) >= max_search_steps or len(docs) >= max_search_steps:
            combined_docs = "\n".join(docs) if docs else "未收集到具体额外资料"
            report = f"【调研简报 - {topic}】\n整理结论：基于检索到的 {len(docs)} 条核心事实：\n{combined_docs}"
            return {
                "summary": report,
                "messages": [AIMessage(content=report)],
            }

        # 否则生成下一个检索关键词
        step_idx = len(queries) + 1
        query = f"{topic} 核心特性 阶段{step_idx}"
        ai_msg = AIMessage(content=f"制定检索计划: {query}")
        return {
            "queries": [query],
            "messages": [ai_msg],
        }

    def search_node(state: ResearcherState) -> dict[str, Any]:
        """子图工具节点：执行检索并将结果追加至私有状态"""
        queries = state.get("queries", [])
        if not queries:
            return {}
        latest_query = queries[-1]
        raw_doc = active_search(latest_query)
        doc_entry = f"[{latest_query}] -> {raw_doc}"
        return {
            "documents": [doc_entry],
            "messages": [HumanMessage(content=f"检索完成: {latest_query}")],
        }

    def route_decision(state: ResearcherState) -> str:
        """根据是否产出最终报告决定结束或继续检索"""
        if state.get("summary"):
            return END
        return "search_executor"

    # 拓扑连线
    builder.add_node("research_planner", planner_node)
    builder.add_node("search_executor", search_node)

    builder.add_edge(START, "research_planner")
    builder.add_conditional_edges(
        "research_planner",
        route_decision,
        {
            "search_executor": "search_executor",
            END: END,
        },
    )
    builder.add_edge("search_executor", "research_planner")

    return compile_agent_graph(builder=builder, checkpointer=checkpointer)
