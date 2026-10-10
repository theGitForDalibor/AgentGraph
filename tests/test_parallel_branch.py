"""
Phase 10 测试: 验证扇出扇入 (Fan-out & Fan-in) 并发分支编排与 Reducer 确定性聚合
"""

import asyncio
import time
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from graph.parallel_graph import (
    build_code_review_parallel_graph,
    build_parallel_branch_graph,
)
from nodes.aggregators import (
    create_dict_aggregator_node,
    create_summary_aggregator_node,
)
from nodes.base import with_error_boundary
from state.agent_state import AgentState


def test_parallel_branch_fan_out_fan_in() -> None:
    """验证扇出扇入拓扑：多个分支并发执行，通过 merge_dict_reducer 汇聚无数据丢失"""

    def branch_a(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"module_a": "ok"}, "scratchpad": ["分支 A 完成"]}

    def branch_b(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"module_b": "ok"}, "scratchpad": ["分支 B 完成"]}

    def branch_c(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"module_c": "ok"}, "scratchpad": ["分支 C 完成"]}

    aggregator = create_summary_aggregator_node(title="多模块并发检测")

    app = build_parallel_branch_graph(
        branch_nodes={
            "branch_a": branch_a,
            "branch_b": branch_b,
            "branch_c": branch_c,
        },
        aggregator_node=aggregator,
    )

    initial_state: AgentState = {
        "messages": [HumanMessage(content="并发检测三模块")],
        "task_goal": "多模块健康检查",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    result = app.invoke(initial_state)

    # 1. 验证所有分支的键均合并成功，无覆盖丢失
    branch_results = result.get("branch_results", {})
    assert branch_results.get("module_a") == "ok"
    assert branch_results.get("module_b") == "ok"
    assert branch_results.get("module_c") == "ok"

    # 2. 验证 append_reducer 原子合并所有分支写入的日志
    scratchpad = result.get("scratchpad", [])
    assert any("分支 A 完成" in log for log in scratchpad)
    assert any("分支 B 完成" in log for log in scratchpad)
    assert any("分支 C 完成" in log for log in scratchpad)


def test_dict_aggregator_calculation() -> None:
    """验证结构化字典汇聚节点：对所有并发分支产出的评分进行综合计算"""

    def audit_1(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"score_1": 80}}

    def audit_2(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"score_2": 90}}

    def calculate_average(results: dict[str, Any]) -> float:
        scores = [v for k, v in results.items() if k.startswith("score_")]
        return sum(scores) / len(scores) if scores else 0.0

    dict_aggregator = create_dict_aggregator_node(
        target_key="average_score",
        reducer_func=calculate_average,
    )

    app = build_parallel_branch_graph(
        branch_nodes={"audit_1": audit_1, "audit_2": audit_2},
        aggregator_node=dict_aggregator,
    )

    initial_state: AgentState = {
        "messages": [],
        "task_goal": "计算评分",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    result = app.invoke(initial_state)
    assert result["branch_results"]["average_score"] == 85.0


def test_code_review_parallel_graph_safe_code() -> None:
    """验证业务参考实现：对合规优质代码进行多维度并发审查"""
    app = build_code_review_parallel_graph()

    safe_python_code = '''
"""数学运算工具模块"""

def compute_square(num: int) -> int:
    """计算整数平方"""
    return num * num
'''

    initial_state: AgentState = {
        "messages": [HumanMessage(content="审查工具代码")],
        "task_goal": "代码审查",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {"target_code": safe_python_code},
    }

    result = app.invoke(initial_state)

    results = result.get("branch_results", {})
    assert results.get("security_status") == "SAFE"
    assert results.get("security_score", 0) >= 80
    assert results.get("style_score", 0) >= 80

    last_msg = str(result["messages"][-1].content)
    assert "审查通过 (APPROVED)" in last_msg


def test_code_review_parallel_graph_dangerous_code() -> None:
    """验证业务参考实现：检出高危漏洞与性能隐患并拒绝通过"""
    app = build_code_review_parallel_graph()

    dangerous_code = """
def run_command(payload):
    password = 'hardcoded_secret'
    eval(payload)
    for i in range(10):
        for j in range(10):
            pass
"""

    initial_state: AgentState = {
        "messages": [HumanMessage(content="审查危险代码")],
        "task_goal": "危险代码审查",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {"target_code": dangerous_code},
    }

    result = app.invoke(initial_state)

    results = result.get("branch_results", {})
    assert results.get("security_status") in ("DANGER", "WARNING")
    assert results.get("security_score", 100) < 60
    assert "eval()" in str(results.get("security_issues"))
    assert results.get("complexity_estimate") == "O(N^2)"

    last_msg = str(result["messages"][-1].content)
    assert "审查不通过" in last_msg


@pytest.mark.asyncio
async def test_parallel_async_execution_speedup() -> None:
    """
    性能基准测试: 验证异步多分支并发调度耗时显著低于串行累加耗时

    3 个分支各自模拟 0.05 秒 I/O 延迟 (串行总和 0.15 秒)。
    在并发超步调度下，总耗时应接近单个最长分支耗时 (约 0.05~0.10 秒)。
    """

    async def async_worker_1(state: AgentState) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"branch_results": {"w1": 1}}

    async def async_worker_2(state: AgentState) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"branch_results": {"w2": 2}}

    async def async_worker_3(state: AgentState) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"branch_results": {"w3": 3}}

    def aggregator(state: AgentState) -> dict[str, Any]:
        return {"scratchpad": ["并发异步执行全部完成"]}

    app = build_parallel_branch_graph(
        branch_nodes={
            "worker_1": async_worker_1,  # type: ignore[dict-item]
            "worker_2": async_worker_2,  # type: ignore[dict-item]
            "worker_3": async_worker_3,  # type: ignore[dict-item]
        },
        aggregator_node=aggregator,
    )

    initial_state: AgentState = {
        "messages": [],
        "task_goal": "并发加速测试",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    start_time = time.perf_counter()
    result = await app.ainvoke(initial_state)
    elapsed = time.perf_counter() - start_time

    assert result["branch_results"] == {"w1": 1, "w2": 2, "w3": 3}
    # 验证并发执行时间远小于 3 个 worker 串行累加的时间 (0.15 秒)
    assert elapsed < 0.13, f"并发执行总耗时 ({elapsed:.3f}s) 超出预期，未能实现有效并发"


def test_parallel_branch_with_checkpointer() -> None:
    """验证带有检查点持久化存储的并发图执行与快照保存"""
    checkpointer = MemorySaver()
    app = build_code_review_parallel_graph(checkpointer=checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": "parallel-session-001"}}
    initial_state: AgentState = {
        "messages": [HumanMessage(content="并发检查")],
        "task_goal": "快照持久化验证",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {"target_code": "def hello(): return 1"},
    }

    app.invoke(initial_state, config=config)

    # 从检查点持久化存储中读取
    state_snapshot = app.get_state(config)
    assert state_snapshot is not None
    assert state_snapshot.values is not None
    assert "security_score" in state_snapshot.values["branch_results"]
    assert "performance_score" in state_snapshot.values["branch_results"]


def test_parallel_branch_error_isolation() -> None:
    """验证错误边界: 单个并发分支发生异常时被安全隔离，不阻断其余分支与汇聚"""

    def normal_branch(state: AgentState) -> dict[str, Any]:
        return {"branch_results": {"normal_key": "success"}}

    @with_error_boundary("faulty_branch")
    def faulty_branch(state: AgentState) -> dict[str, Any]:
        raise RuntimeError("模拟外部服务连接超时")

    aggregator = create_summary_aggregator_node(title="容错汇聚")

    app = build_parallel_branch_graph(
        branch_nodes={
            "normal_branch": normal_branch,
            "faulty_branch": faulty_branch,
        },
        aggregator_node=aggregator,
    )

    initial_state: AgentState = {
        "messages": [],
        "task_goal": "容错测试",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    result = app.invoke(initial_state)

    # 正常分支数据依然成功汇聚
    assert result["branch_results"].get("normal_key") == "success"
    # 异常分支错误被捕获并记录在 scratchpad / metadata 中，未击垮整体图流程
    scratchpad = result.get("scratchpad", [])
    assert any("ERROR in faulty_branch" in log for log in scratchpad)
