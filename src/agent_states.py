import json
from src.utils import *
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages



# ------------------------------------- Agent States ------------------------------------

class Text2SQLState(TypedDict):
    messages: Annotated[list, add_messages]
    sql_queries: Annotated[str, save_last]
    loop_again: Annotated[bool, save_last]
    exception_message: Annotated[str, save_last]
    result_data: Annotated[list, save_last]

class InsightState(TypedDict):
    messages: Annotated[list, add_messages]
    insights: Annotated[str, save_last]
    loop_again: Annotated[bool, save_last]
    exception_message: Annotated[str, save_last]
    json_insights: Annotated[json, save_last]


class ChatOrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]

class GraphVisualizationState(TypedDict):
    messages: Annotated[list, add_messages]
