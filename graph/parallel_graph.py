"""
Jarvis Agent Pro - 并发分支图装配器 (Parallel Branch Graph Builder)

实现 Phase 10 Parallel Branch 核心架构：
在单个 Pregel 超步 (Superstep) 中，实现扇出 (Fan-out) 并发分发与扇入 (Fan-in) 聚合。
并发节点执行时只返回增量字典，框架在超步末期通过 merge_dict_reducer 与 append_reducer
完成确定性 (Deterministic)、无锁 (Lock-free) 的并发状态汇聚。
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph

from graph.builder import compile_agent_graph, create_agent_graph_builder
from nodes.aggregators import create_summary_aggregator_node
from nodes.base import NodeFunction, with_error_boundary
from state.agent_state import AgentState


def build_parallel_branch_graph(
    branch_nodes: dict[str, NodeFunction],
    aggregator_node: NodeFunction,
    dispatcher_node: NodeFunction | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装并编译通用的扇出扇入并发分支状态图 (Fan-out & Fan-in Graph)

    Args:
        branch_nodes: 并发分支字典映射 {节点名称: 节点函数}
        aggregator_node: 扇入汇聚节点函数
        dispatcher_node: 可选的扇出前置分发节点 (若为 None 则从 START 直接并发扇出)
        checkpointer: 可选的检查点持久化存储

    Returns:
        CompiledStateGraph: 支持原生无锁并发调度编译状态图
    """
    if not branch_nodes:
        raise ValueError("构建并发分支图必须至少提供一个并发分支节点 (branch_nodes 不能为空)")

    builder = create_agent_graph_builder(AgentState)

    # 1. 注册扇入汇聚节点
    builder.add_node("aggregator", aggregator_node)  # type: ignore[call-overload]

    # 2. 注册前置分发节点 (若存在)
    if dispatcher_node:
        builder.add_node("dispatcher", dispatcher_node)  # type: ignore[call-overload]
        builder.add_edge(START, "dispatcher")
        fan_out_source = "dispatcher"
    else:
        fan_out_source = START

    # 3. 注册各并发分支并建立扇出与扇入连线
    for branch_name, branch_func in branch_nodes.items():
        builder.add_node(branch_name, branch_func)  # type: ignore[call-overload]
        # 扇出边: 源节点 -> 各并发分支
        builder.add_edge(fan_out_source, branch_name)
        # 扇入边: 各并发分支 -> 汇聚节点
        builder.add_edge(branch_name, "aggregator")

    # 4. 汇聚节点输出至终态
    builder.add_edge("aggregator", END)

    return compile_agent_graph(builder=builder, checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# 业务参考实现：多维度代码质量与安全并发审查图 (Parallel Code Review)
# ---------------------------------------------------------------------------


@with_error_boundary("security_auditor")
def security_auditor_node(state: AgentState) -> dict[str, Any]:
    """并发分支 1: 代码安全漏洞审计"""
    task = state.get("task_goal", "")
    metadata = state.get("metadata", {})
    code = str(metadata.get("target_code") or task)

    risk_flags = []
    score = 100
    if "eval(" in code:
        risk_flags.append("高危动态求值: 发现 eval() 调用")
        score -= 40
    if "os.system(" in code or "subprocess" in code:
        risk_flags.append("系统命令执行: 发现外部子进程执行风险")
        score -= 30
    if "password" in code.lower() or "secret" in code.lower():
        risk_flags.append("凭据泄露风险: 发现敏感关键字硬编码")
        score -= 20

    status = "SAFE" if score >= 80 else ("WARNING" if score >= 60 else "DANGER")
    audit_summary = f"状态: {status} (安全得分: {score}/100, 检出风险: {len(risk_flags)} 项)"

    return {
        "branch_results": {
            "security_score": score,
            "security_status": status,
            "security_issues": risk_flags,
            "security_summary": audit_summary,
        },
        "scratchpad": [f"安全审计完成: {audit_summary}"],
    }


@with_error_boundary("performance_profiler")
def performance_profiler_node(state: AgentState) -> dict[str, Any]:
    """并发分支 2: 代码性能与复杂度分析"""
    task = state.get("task_goal", "")
    metadata = state.get("metadata", {})
    code = str(metadata.get("target_code") or task)

    perf_notes = []
    complexity = "O(1)"
    score = 95

    if "for " in code:
        nested_count = code.count("for ")
        if nested_count >= 2:
            complexity = f"O(N^{nested_count})"
            score -= 25
            perf_notes.append("检测到多层嵌套循环，建议重构或向量化优化")
        else:
            complexity = "O(N)"
            score -= 10
            perf_notes.append("常规单层循环迭代")
    if "while True" in code:
        perf_notes.append("检测到潜在无限循环构造，需验证退出熔断")
        score -= 15

    perf_summary = f"时间复杂度预估: {complexity} (效率评分: {score}/100)"
    return {
        "branch_results": {
            "performance_score": score,
            "complexity_estimate": complexity,
            "performance_notes": perf_notes,
            "performance_summary": perf_summary,
        },
        "scratchpad": [f"性能分析完成: {perf_summary}"],
    }


@with_error_boundary("style_compliance")
def style_compliance_node(state: AgentState) -> dict[str, Any]:
    """并发分支 3: PEP8 编码风格与规范校验"""
    task = state.get("task_goal", "")
    metadata = state.get("metadata", {})
    code = str(metadata.get("target_code") or task)

    issues = []
    score = 90
    if '"""' not in code and "'''" not in code:
        issues.append("缺少标准模块/函数文档字符串 (Docstring)")
        score -= 15
    if any(len(line) > 100 for line in code.splitlines()):
        issues.append("存在超过 100 字符的过长代码行")
        score -= 10

    style_summary = f"PEP8 规范度得分: {score}/100 (发现瑕疵: {len(issues)} 处)"
    return {
        "branch_results": {
            "style_score": score,
            "style_issues": issues,
            "style_summary": style_summary,
        },
        "scratchpad": [f"风格审查完成: {style_summary}"],
    }


def review_aggregator_formatter(results: dict[str, Any]) -> str:
    """代码多维审查汇聚格式化器"""
    sec = results.get("security_summary", "安全审计未完成")
    perf = results.get("performance_summary", "性能分析未完成")
    style = results.get("style_summary", "规范审查未完成")

    sec_score = int(results.get("security_score", 0))
    perf_score = int(results.get("performance_score", 0))
    style_score = int(results.get("style_score", 0))

    avg_score = round((sec_score * 0.5 + perf_score * 0.3 + style_score * 0.2), 1)
    passed = sec_score >= 60 and avg_score >= 70
    decision = (
        "【审查通过 (APPROVED)】" if passed else "【审查不通过，建议重构 (CHANGES REQUESTED)】"
    )

    return (
        f"综合评估决议: {decision} (加权综合得分: {avg_score}/100)\n\n"
        f"1. 安全维度 (权重 50%): {sec}\n"
        f"2. 性能维度 (权重 30%): {perf}\n"
        f"3. 风格维度 (权重 20%): {style}\n"
    )


def build_code_review_parallel_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装并编译工业级代码多维度并行审查图 (Parallel Code Review Graph)

    拓扑流程：
    START -> [security_auditor, performance_profiler, style_compliance] (并行超步扇出)
          -> review_aggregator (扇入汇总生成决议) -> END
    """
    branches: dict[str, NodeFunction] = {
        "security_auditor": security_auditor_node,
        "performance_profiler": performance_profiler_node,
        "style_compliance": style_compliance_node,
    }

    aggregator = create_summary_aggregator_node(
        title="自动化多维度代码并行审查报告",
        custom_formatter=review_aggregator_formatter,
    )

    def dispatcher(state: AgentState) -> dict[str, Any]:
        return {
            "scratchpad": ["Dispatcher 调度器: 启动 3 维度代码并行审计流程 (Fan-out)"],
        }

    return build_parallel_branch_graph(
        branch_nodes=branches,
        aggregator_node=aggregator,
        dispatcher_node=dispatcher,
        checkpointer=checkpointer,
    )
