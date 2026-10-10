"""
Jarvis Agent Pro - 图拓扑组装与编排层 (StateGraph Layer)

负责声明有向图拓扑、静态边 (Static Edge)、条件边 (Conditional Edge)、
路由分发 (Router)、子图模式 (Subgraph) 以及图生命周期编译 (Compile)。
"""

from langgraph.graph import END, START

from graph.builder import (
    compile_agent_graph,
    create_agent_graph_builder,
)
from graph.checkpointed_graph import compile_with_checkpointer
from graph.edges import (
    build_linear_agent_graph,
    connect_sequence,
    export_mermaid_diagram,
)
from graph.hitl_graph import build_hitl_agent_graph
from graph.parent_graph import (
    ROUTER_CODE,
    ROUTER_RESEARCH,
    ROUTER_SYNTHESIZE,
    build_hierarchical_parent_graph,
)
from graph.react_graph import build_react_agent_graph
from graph.router import (
    ROUTER_ACTION_END,
    ROUTER_ACTION_TOOLS,
    route_planner_decision,
)
from graph.subgraphs.coder import CoderState, build_coder_subgraph
from graph.subgraphs.researcher import ResearcherState, build_researcher_subgraph

__version__ = "0.1.0"
__all__ = [
    "CoderState",
    "END",
    "ROUTER_ACTION_END",
    "ROUTER_ACTION_TOOLS",
    "ROUTER_CODE",
    "ROUTER_RESEARCH",
    "ROUTER_SYNTHESIZE",
    "ResearcherState",
    "START",
    "__version__",
    "build_coder_subgraph",
    "build_hierarchical_parent_graph",
    "build_hitl_agent_graph",
    "build_linear_agent_graph",
    "build_react_agent_graph",
    "build_researcher_subgraph",
    "compile_agent_graph",
    "compile_with_checkpointer",
    "connect_sequence",
    "create_agent_graph_builder",
    "export_mermaid_diagram",
    "route_planner_decision",
]
