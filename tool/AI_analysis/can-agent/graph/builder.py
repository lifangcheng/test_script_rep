from __future__ import annotations

from langgraph.graph import StateGraph

from graph.nodes.ai_analyze import ai_analyze
from graph.nodes.anomaly_detect import anomaly_detect
from graph.nodes.build_dataframe import build_dataframe
from graph.nodes.decode_dbc import decode_dbc
from graph.nodes.load_skills import load_skills
from graph.nodes.parse_blf import parse_blf
from graph.nodes.report_generate import report_generate
from graph.nodes.signal_index import signal_index
from graph.nodes.summarize import summarize
from graph.nodes.validate_input import validate_input
from graph.state import CANState


NODE_ORDER = [
    "validate_input",
    "load_skills",
    "parse_blf",
    "decode_dbc",
    "build_dataframe",
    "anomaly_detect",
    "summarize",
    "report_generate",
    "signal_index",
    "ai_analyze",
]


def build_graph() -> StateGraph:
    g: StateGraph = StateGraph(CANState)

    g.add_node("validate_input", validate_input)
    g.add_node("load_skills", load_skills)
    g.add_node("parse_blf", parse_blf)
    g.add_node("decode_dbc", decode_dbc)
    g.add_node("build_dataframe", build_dataframe)
    g.add_node("anomaly_detect", anomaly_detect)
    g.add_node("summarize", summarize)
    g.add_node("report_generate", report_generate)
    g.add_node("signal_index", signal_index)
    g.add_node("ai_analyze", ai_analyze)

    # strict order
    for i in range(len(NODE_ORDER) - 1):
        g.add_edge(NODE_ORDER[i], NODE_ORDER[i + 1])

    g.set_entry_point("validate_input")
    g.set_finish_point("ai_analyze")

    return g


def compile_graph():
    return build_graph().compile()
