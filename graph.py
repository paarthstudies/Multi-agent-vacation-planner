"""
TripCrew Backend Platform - Phase 1 MVP
LangGraph Assembly, Conditional Routing, and Pipeline Orchestration
"""

import uuid
from typing import Optional, Dict, Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from models import TripBrief, ClientInfo
from agents import (
    intake_agent,
    itinerary_agent,
    budget_agent,
    document_agent,
)


def route_after_intake(state: TripBrief) -> str:
    """
    Conditional routing function:
    - If required fields are missing, status is 'needs_clarification' -> short-circuit to END.
    - Otherwise, progress to 'itinerary' generation.
    """
    if state.status == "needs_clarification":
        return "end"
    return "itinerary"


def build_trip_graph(use_memory: bool = True):
    """
    Constructs and compiles the StateGraph for the TripCrew Vacation Planner.

    Flow:
    [START] -> intake_agent
                   |
         (conditional route)
         /                 \
    (missing info)      (complete info)
        /                     \
      [END]              itinerary_agent
                               |
                          budget_agent
                               |
                          document_agent
                               |
                             [END]
    """
    workflow = StateGraph(TripBrief)

    # 1. Register discrete agent nodes
    workflow.add_node("intake", intake_agent)
    workflow.add_node("itinerary", itinerary_agent)
    workflow.add_node("budget", budget_agent)
    workflow.add_node("document", document_agent)

    # 2. Set Entrypoint
    workflow.set_entry_point("intake")

    # 3. Add Conditional Edge from Intake
    workflow.add_conditional_edges(
        "intake",
        route_after_intake,
        {
            "end": END,
            "itinerary": "itinerary",
        },
    )

    # 4. Add Linear Edges for downstream execution
    workflow.add_edge("itinerary", "budget")
    workflow.add_edge("budget", "document")
    workflow.add_edge("document", END)

    # 5. Compile with optional in-memory checkpointer
    if use_memory:
        checkpointer = MemorySaver()
        compiled_graph = workflow.compile(checkpointer=checkpointer)
    else:
        compiled_graph = workflow.compile()

    return compiled_graph


# Singleton compiled graph instance
trip_planner_graph = build_trip_graph(use_memory=True)


def run_inquiry_pipeline(
    raw_message: str,
    session_id: Optional[str] = None,
    client_name: Optional[str] = None,
    contact: Optional[str] = None,
) -> TripBrief:
    """
    Executes the multi-agent graph with the customer inquiry.
    Handles thread-level state memory using session_id.
    """
    session = session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session}}

    initial_state = TripBrief(
        raw_inquiry=raw_message,
        session_id=session,
        client=ClientInfo(
            name=client_name or "Valued Traveler",
            contact=contact,
        ),
    )

    # Execute LangGraph pipeline
    output_state = trip_planner_graph.invoke(initial_state, config=config)

    # Ensure return value is parsed into Pydantic model
    if isinstance(output_state, TripBrief):
        return output_state
    return TripBrief(**output_state)
