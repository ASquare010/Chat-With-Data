import json
from typing import Literal, List, Optional
from langchain_openai import ChatOpenAI
from requests import JSONDecodeError
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from agentic.agent_states import Text2SQLState
from agentic.prompts.agent_templates import (
    make_sys_prompt_text_to_sql,
    make_txt2sql_exec_format,
    make_txt2sql_exec_sql,
)
from common.utils.postgres_client import PostgresClient
from common.models.api_models import Text2SQLOutput
from common.models.db_metadata import SchemaMetadata, DatabaseResult


class Text2SQLAgent:
    """Generic Agent to convert text to SQL and execute it on a database."""

    def __init__(
        self,
        db_client: PostgresClient,
        metadata: SchemaMetadata,
        database_type: str = "PostgreSQL:18",
        max_try: int = 3,
    ):
        self.llm = ChatOpenAI(
            model="gpt-5",
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.client = db_client
        self.metadata = metadata
        self.database_type = database_type
        self.max_try = max_try
        self.loop_count = 0
        self.compile()

    def text_to_sql_node(self, state: Text2SQLState):
        """Generate SQL queries from user prompt and previous messages."""
        mem = state["messages"].copy()
        issue_prompt = state.get("exception_message")
        if issue_prompt is not None and state.get("loop_again", False):
            mem.append(HumanMessage(str(issue_prompt)))

        result = self.llm.invoke(mem)
        return {
            "messages": [result],
            "sql_queries": Text2SQLOutput.model_validate_json(result.content),
            "loop_again": False,
        }

    def execute_sql_node(self, state: Text2SQLState):
        """Execute the generated SQL queries and handle exceptions."""
        self.loop_count += 1
        current_sql_query = ""
        result: List = []
        try:
            sql_queries = state["sql_queries"]
            try:
                for sql_query in sql_queries.sql:
                    current_sql_query = sql_query
                    db_result = self.client.execute(sql_query)
                    result.append(db_result)
                return {"loop_again": False, "result_data": result}

            except Exception as e:
                exception_message = make_txt2sql_exec_sql(
                    sql=current_sql_query,
                    exception_message=str(e),
                    db_type="PostgreSQL:18",
                )
                return {"loop_again": True, "exception_message": exception_message}

        except JSONDecodeError as e:
            exception_message = make_txt2sql_exec_format(
                llm_output=sql_queries.model_dump_json(include=4),
                exception_message=str(e),
            )
            return {"loop_again": True, "exception_message": exception_message}

    def loop_again_condition(self, state: Text2SQLState) -> Literal["text_to_sql", END]:
        """Decide whether to loop again or end based on the state."""
        if self.loop_count >= self.max_try:
            return END
        return "text_to_sql" if state.get("loop_again", False) else END

    def compile(self):
        """Compile the state graph for the Text2SQL agent."""
        builder = StateGraph(Text2SQLState)
        builder.add_node("text_to_sql", self.text_to_sql_node)
        builder.add_node("execute_sql", self.execute_sql_node)

        # Regular flow
        builder.set_entry_point("text_to_sql")
        builder.add_edge("text_to_sql", "execute_sql")
        builder.add_conditional_edges("execute_sql", self.loop_again_condition)

        # Compile the graph
        self.graph = builder.compile()

    def invoke(
        self, user_prompt: str, metadata: Optional[SchemaMetadata] = None
    ) -> List[DatabaseResult]:
        """Invoke the Text2SQL agent."""
        self.loop_count = 0
        system_prompt = make_sys_prompt_text_to_sql(
            metadata=(metadata if metadata else self.metadata),
            db_type=self.database_type,
        )
        result: Text2SQLState = self.graph.invoke(
            {
                "messages": [system_prompt, HumanMessage(user_prompt)],
            }
        )
        return result.get("result_data", [])


if __name__ == "__main__":

    from pathlib import Path

    # Compute the repo root dynamically (4 levels up from this file)
    repo_root = Path(__file__).resolve().parents[3]

    # Build the correct path to metadata_dump.json
    example_metadata_path = repo_root / "db_faker" / "data" / "metadata_dump.json"

    if not example_metadata_path.exists():
        raise FileNotFoundError(
            f"Example metadata file not found: {example_metadata_path}"
        )

    with example_metadata_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    example_metadata = SchemaMetadata.model_validate(data)
    client = PostgresClient()
    client.connect()
    agent = Text2SQLAgent(db_client=client, metadata=example_metadata)
    metadata = example_metadata.model_copy(deep=True)
    print(agent.invoke("Give me 2 tables 5 rows", metadata.filter_tables(["calls"])))
    print(agent.loop_count)
