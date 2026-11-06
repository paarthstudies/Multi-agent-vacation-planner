"""
TripCrew Backend Platform - Phase 2 (Quality)
LangGraph Assembly, Critic Validation Routing, and Re-planning Loop
"""

import uuid
from typing import Optional, Dict, Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from models import TripBrief, ClientInfo
from agents import (
    intake_agent,
    itinerary_agent,
    validator_agent,
    budget_agent,
    document_agent,
)


def route_after_intake(state: TripBrief) -> str:
    """
    Conditional routing from Intake:
    - If required fields are missing, status is 'needs_clarification' -> short-circuit to END.
    - Otherwise, progress to 'itinerary' generation.
    """
    if state.status == "needs_clarification":
        return "end"
    return "itinerary"


def route_after_validator(state: TripBrief) -> str:
    """
    Conditional routing from Critic Validator (Re-planning Loop):
    - If itinerary is valid (no critical violations) -> proceed to 'budget'.
    - If invalid and replan_count < max_retries -> route back to 'itinerary' for revision.
    - If invalid and replan_count >= max_retries -> proceed to 'budget' (prevents infinite loops).
    """
    val = state.validation_result
    if val is None or val.is_valid:
        return "budget"

    if state.replan_count < state.max_retries:
        return "itinerary"

    # Max retries exceeded; proceed to budget with best effort
    return "budget"


def build_trip_graph(use_memory: bool = True):
    """
    Constructs and compiles the StateGraph for the TripCrew Quality Architecture.

    Flow:
    [START] -> intake_agent
                   |
         (conditional route)
         /                 \
    (missing info)      (complete info)
        /                     \
      [END]              itinerary_agent <-------------------+
                               |                             |
                         validator_agent (Critic Node)       |
                               |                             |
                      (conditional routing)                  |
                      /                   \                  |
               (is_valid: True)    (is_valid: False &        |
                     or            replan_count < max_retries)+
           (replan >= max_retries)
                    |
               budget_agent (Live APIs / Amadeus sandbox)
                    |
               document_agent (PDF with Quality Score & Weather)
                    |
                  [END]
    """
    workflow = StateGraph(TripBrief)

    # 1. Register discrete agent nodes
    workflow.add_node("intake", intake_agent)
    workflow.add_node("itinerary", itinerary_agent)
    workflow.add_node("validator", validator_agent)
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

    # 4. Itinerary leads directly to Critic Validator
    workflow.add_edge("itinerary", "validator")

    # 5. Add Conditional Edge from Validator (The Re-planning Quality Loop)
    workflow.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "budget": "budget",
            "itinerary": "itinerary",
        },
    )

    # 6. Budget leads to Document and END
    workflow.add_edge("budget", "document")
    workflow.add_edge("document", END)

    # 7. Compile with memory checkpointer
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
    max_retries: int = 3,
) -> TripBrief:
    """
    Executes the multi-agent graph with the customer inquiry.
    Handles thread-level state memory using session_id and recursion bounds.
    """
    session = session_id or str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": session},
        "recursion_limit": 50,
    }

    initial_state = TripBrief(
        raw_inquiry=raw_message,
        session_id=session,
        max_retries=max_retries,
        client=ClientInfo(
            name=client_name or "Valued Traveler",
            contact=contact,
        ),
    )

    # Execute LangGraph pipeline
    output_state = trip_planner_graph.invoke(initial_state, config=config)

    if isinstance(output_state, TripBrief):
        return output_state
    return TripBrief(**output_state)
