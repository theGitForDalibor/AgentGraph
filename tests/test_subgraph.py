"""
Phase 9 测试: 验证子图模式 (Subgraph)、分层多智能体编排与状态黑盒隔离
"""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from graph.parent_graph import build_hierarchical_parent_graph
from graph.subgraphs.coder import (
    CoderState,
    build_coder_subgraph,
    default_python_syntax_tester,
)
from graph.subgraphs.researcher import (
    ResearcherState,
    build_researcher_subgraph,
)
from state.agent_state import AgentState


def test_researcher_subgraph_standalone() -> None:
    """验证 Researcher 调研子图独立执行并完成多轮检索与报告提炼"""
    mock_search = MagicMock(return_value="LangGraph 是轻量级有向图调度引擎。")
    app = build_researcher_subgraph(search_tool=mock_search, max_search_steps=2)

    initial_state: ResearcherState = {
        "topic": "Pregel 调度模型",
        "queries": [],
        "documents": [],
        "messages": [],
        "summary": None,
    }

    result = app.invoke(initial_state)

    assert result["summary"] is not None
    assert "Pregel 调度模型" in result["summary"]
    assert len(result["queries"]) >= 1
    assert len(result["documents"]) >= 1
    assert mock_search.called


def test_coder_subgraph_standalone_passes() -> None:
    """验证 Coder 子图独立执行并成功通过静态语法自测"""
    app = build_coder_subgraph(max_revisions=2)

    initial_state: CoderState = {
        "requirement": "实现斐波那契数列函数",
        "research_context": None,
        "code_snippet": None,
        "test_results": None,
        "revision_count": 0,
        "max_revisions": 2,
        "status": "drafting",
        "messages": [],
    }

    result = app.invoke(initial_state)

    assert result["status"] == "completed"
    assert result["code_snippet"] is not None
    assert "def solution():" in result["code_snippet"]
    passed, _ = default_python_syntax_tester(result["code_snippet"])
    assert passed is True


def test_coder_subgraph_revision_loop() -> None:
    """验证 Coder 子图自修复闭环：首轮失败，第二轮修复通过"""
    test_attempts = 0

    def mock_tester(code: str) -> tuple[bool, str]:
        nonlocal test_attempts
        test_attempts += 1
        if test_attempts == 1:
            return False, "SyntaxError 在第 2 行: 模拟语法错误"
        return True, "修复后测试全部通过"

    app = build_coder_subgraph(test_runner=mock_tester, max_revisions=3)

    initial_state: CoderState = {
        "requirement": "自修复测试用例",
        "research_context": None,
        "code_snippet": None,
        "test_results": None,
        "revision_count": 0,
        "max_revisions": 3,
        "status": "drafting",
        "messages": [],
    }

    result = app.invoke(initial_state)

    assert result["status"] == "completed"
    assert result["revision_count"] == 2
    assert test_attempts == 2
    assert "已修复语法错误" in (result["code_snippet"] or "")


def test_coder_subgraph_max_revision_limit() -> None:
    """验证 Coder 子图达到最大修复上限后安全熔断结束 (防止死循环)"""

    def always_fail_tester(code: str) -> tuple[bool, str]:
        return False, "测试持续报错: 无法修复的逻辑缺陷"

    app = build_coder_subgraph(test_runner=always_fail_tester, max_revisions=2)

    initial_state: CoderState = {
        "requirement": "不可能完成的复杂任务",
        "research_context": None,
        "code_snippet": None,
        "test_results": None,
        "revision_count": 0,
        "max_revisions": 2,
        "status": "drafting",
        "messages": [],
    }

    result = app.invoke(initial_state)

    assert result["status"] == "failed"
    assert result["revision_count"] == 2


def test_subgraph_state_isolation() -> None:
    """
    核心架构验证: 验证父图与子图之间的状态黑盒隔离性

    子图内部高频中间变量 (queries, documents, 细粒度草稿) 严禁污染父图的消息历史。
    """
    app = build_hierarchical_parent_graph()

    parent_initial: AgentState = {
        "messages": [HumanMessage(content="调研并开发状态图引擎")],
        "task_goal": "状态图引擎技术调研与原型实现",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    final_result = app.invoke(parent_initial)

    # 1. 父图只追加了最终汇总响应，没有混入子图内部的零散 prompt/search 消息
    parent_messages = final_result.get("messages", [])
    assert len(parent_messages) == 2  # 初始 HumanMessage + 最终综合 AIMessage
    assert isinstance(parent_messages[-1], AIMessage)
    assert "Jarvis 多智能体协同交付报告" in str(parent_messages[-1].content)

    # 2. 检查父图根级别绝不包含子图私有键 (严格模式隔离)
    assert "queries" not in final_result
    assert "documents" not in final_result
    assert "revision_count" not in final_result


def test_hierarchical_parent_graph_pipeline() -> None:
    """验证父图协调全流程：分层调度各子图并汇聚所有阶段产物"""
    app = build_hierarchical_parent_graph()

    parent_initial: AgentState = {
        "messages": [HumanMessage(content="开发安全计算器")],
        "task_goal": "安全计算器实现",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    result = app.invoke(parent_initial)

    branch_results = result.get("branch_results", {})
    assert "research_summary" in branch_results
    assert "code_artifact" in branch_results
    assert branch_results.get("coder_status") == "completed"

    scratchpad = result.get("scratchpad", [])
    assert any("Researcher 子图交付成果" in entry for entry in scratchpad)
    assert any("Coder 子图交付成果" in entry for entry in scratchpad)


def test_hierarchical_parent_graph_with_checkpointer() -> None:
    """验证分层父图在挂载持久化检查点时的多超步状态快照与恢复"""
    checkpointer = MemorySaver()
    app = build_hierarchical_parent_graph(checkpointer=checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": "hierarchical-session-001"}}
    parent_initial: AgentState = {
        "messages": [HumanMessage(content="多智能体协同设计")],
        "task_goal": "微服务健康探针",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    app.invoke(parent_initial, config=config)

    # 从检查点中读取保存的快照
    saved_snapshot = app.get_state(config)
    assert saved_snapshot is not None
    assert saved_snapshot.values is not None
    assert "research_summary" in saved_snapshot.values["branch_results"]
    assert "code_artifact" in saved_snapshot.values["branch_results"]
