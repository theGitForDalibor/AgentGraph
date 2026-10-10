"""
Jarvis Agent Pro - 分层多智能体主管父图 (Hierarchical Supervisor Parent Graph)

实现 Phase 9 Subgraph 核心架构：
父图扮演主管 (Supervisor / Orchestrator) 角色，协调多个专职子图 (Researcher、Coder)。
各子图作为原子节点嵌入，在完全隔离的私有状态中完成高频推演与自我修复，
并将最终成果安全汇聚至父图的 branch_results 与 scratchpad，杜绝上下文污染。
"""

from collections.abc import Callable
from typing import Any, Final, Literal

from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph

from graph.builder import compile_agent_graph, create_agent_graph_builder
from graph.subgraphs.coder import CoderState, build_coder_subgraph
from graph.subgraphs.researcher import ResearcherState, build_researcher_subgraph
from state.agent_state import AgentState

ROUTER_RESEARCH: Final = "researcher"
ROUTER_CODE: Final = "coder"
ROUTER_SYNTHESIZE: Final = "synthesizer"


def build_hierarchical_parent_graph(
    researcher_subgraph: CompiledStateGraph | None = None,
    coder_subgraph: CompiledStateGraph | None = None,
    supervisor_decider: Callable[[AgentState], str] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装并编译分层多智能体主管父图 (Hierarchical Parent Graph)

    Args:
        researcher_subgraph: 专职调研子图实例 (默认自动构建)
        coder_subgraph: 专职代码实现子图实例 (默认自动构建)
        supervisor_decider: 自定义主管决策函数，决定下一步调度哪一个专职子图
        checkpointer: 可选的父图检查点存储器

    Returns:
        CompiledStateGraph: 具备子图分层调度能力的编译状态图
    """
    active_researcher = researcher_subgraph or build_researcher_subgraph()
    active_coder = coder_subgraph or build_coder_subgraph()

    builder = create_agent_graph_builder(AgentState)

    def supervisor_node(state: AgentState) -> dict[str, Any]:
        """主管节点：审查全局任务目标与当前各子图成果，推进多智能体工作计划"""
        results = state.get("branch_results", {})
        has_research = "research_summary" in results
        has_code = "code_artifact" in results

        if not has_research:
            next_action = "调度 Researcher 子图展开前期背景与技术调研"
        elif not has_code:
            next_action = "调度 Coder 子图基于调研成果进行代码实现与自测"
        else:
            next_action = "子图协作任务已全部就绪，准备汇聚最终成果"

        return {
            "scratchpad": [f"Supervisor 主管分析: {next_action}"],
        }

    def researcher_node(state: AgentState) -> dict[str, Any]:
        """
        子图适配节点：在完全隔离的上下文内调用 Researcher 子图

        核心机制：子图内部的高频检索 queries 与 raw documents 保留在子图内部，
        只将最终产出的 summary 提取并合并至父图 branch_results。
        """
        topic = state.get("task_goal") or "通用技术调研"
        sub_input: ResearcherState = {
            "topic": topic,
            "queries": [],
            "documents": [],
            "messages": [],
            "summary": None,
        }

        # 调用黑盒独立子图
        sub_output = active_researcher.invoke(sub_input)
        summary = str(sub_output.get("summary") or "未生成有效调研简报")

        return {
            "branch_results": {"research_summary": summary},
            "scratchpad": [f"Researcher 子图交付成果 (长度: {len(summary)})"],
        }

    def coder_node(state: AgentState) -> dict[str, Any]:
        """
        子图适配节点：在完全隔离的上下文内调用 Coder 子图

        核心机制：将父图任务与前置调研简报传递给 Coder，
        子图内部的多次 Draft/Test/Revise 迭代不直接写入父图 messages。
        """
        requirement = state.get("task_goal") or "功能模块研发"
        research_context = state.get("branch_results", {}).get("research_summary")

        sub_input: CoderState = {
            "requirement": requirement,
            "research_context": research_context,
            "code_snippet": None,
            "test_results": None,
            "revision_count": 0,
            "max_revisions": 3,
            "status": "drafting",
            "messages": [],
        }

        # 调用黑盒独立子图
        sub_output = active_coder.invoke(sub_input)
        code = str(sub_output.get("code_snippet") or "# 未生成有效代码")
        status = str(sub_output.get("status") or "completed")

        return {
            "branch_results": {
                "code_artifact": code,
                "coder_status": status,
            },
            "scratchpad": [f"Coder 子图交付成果 (状态: {status})"],
        }

    def synthesizer_node(state: AgentState) -> dict[str, Any]:
        """成果汇总节点：汇聚所有子图输出，向用户交付最终综合回答"""
        goal = state.get("task_goal", "")
        results = state.get("branch_results", {})
        research = results.get("research_summary", "无调研成果")
        code = results.get("code_artifact", "无代码成果")

        final_content = (
            f"【Jarvis 多智能体协同交付报告】\n"
            f"任务目标: {goal}\n\n"
            f"1. 调研分析总结:\n{research}\n\n"
            f"2. 代码实现成果:\n```python\n{code}\n```"
        )

        return {
            "messages": [AIMessage(content=final_content)],
            "scratchpad": ["Supervisor 完成全量多智能体成果汇总与交付"],
        }

    def default_supervisor_route(
        state: AgentState,
    ) -> Literal["researcher", "coder", "synthesizer"]:
        """主管路由逻辑：根据现有分支结果决定调用哪个子图或结束"""
        results = state.get("branch_results", {})
        if "research_summary" not in results:
            return ROUTER_RESEARCH
        if "code_artifact" not in results:
            return ROUTER_CODE
        return ROUTER_SYNTHESIZE

    route_func = supervisor_decider or default_supervisor_route

    # 注册节点
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("synthesizer", synthesizer_node)

    # 入口与条件路由
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_func,
        {
            ROUTER_RESEARCH: "researcher",
            ROUTER_CODE: "coder",
            ROUTER_SYNTHESIZE: "synthesizer",
        },
    )

    # 各子图完成工作后回环至主管，进行下一步推演
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("coder", "supervisor")
    builder.add_edge("synthesizer", END)

    return compile_agent_graph(builder=builder, checkpointer=checkpointer)
