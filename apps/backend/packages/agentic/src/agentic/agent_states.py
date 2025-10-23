from typing import Annotated, Optional, List
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from common.models.db_metadata import DatabaseResult
from common.models.api_models import Text2SQLOutput


# ------------------------------------- Agent States ------------------------------------


class Text2SQLState(TypedDict):
    messages: Annotated[List, add_messages]
    loop_again: bool = False
    exception_message: str = ""
    sql_queries: Optional[Text2SQLOutput] = None
    result_data: List[DatabaseResult] = []


class ChatOrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]


class GraphVisualizationState(TypedDict):
    messages: Annotated[list, add_messages]
