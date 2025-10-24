import json
import traceback
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage
from agentic.prompts.agent_templates import make_sys_prompt_orch
from agentic.agent_states import ChatOrchestratorState
from agentic.text_to_sql import Text2SQLAgent
from agentic.graph_visualization import GraphVisualization
from common.models.db_metadata import SchemaMetadata
from common.utils.postgres_client import PostgresClient


# ----------------------------------------- Agents --------------------------------------


class ChatOrchestrator:
    """Orchestrates multiple agents to handle complex user queries."""

    def __init__(
        self,
        db_client: PostgresClient,
        metadata: SchemaMetadata,
        db_type: str = "PostgreSQL:18",
    ):

        tools = [self.text_to_sql_tool, self.graph_visualization_tool]
        self.llm = ChatOpenAI(model="gpt-5").bind_tools(tools)
        self.tool_node = ToolNode(tools=tools)
        self.txt2sql = Text2SQLAgent(db_client, metadata, db_type)
        self.visu = GraphVisualization(db_client, metadata, db_type)
        self.metadata = metadata
        self.base64_image = ""
        self.compile()

    def text_to_sql_tool(self, query: str, table_names: list[str]) -> list:
        """
        Converts natural language text to SQL queries.

        Parameters:
            query (str): The natural language description for the desired SQL query.
            table_names (list[str]): A list of table names what will be used for this query.

        Returns:
            list: A list of generated SQL query strings and their corresponding results.
        """
        print("txt2sql_tool", query, table_names)
        metadata = self.metadata.model_copy(deep=True)

        try:
            raw = self.txt2sql.invoke(query, metadata.filter_tables(table_names))
        except Exception as e:
            traceback.print_exc()
            return [json.dumps({"error": str(e)})]

        result = []
        for r in raw:
            result.append(r.model_dump_json(indent=4))
        print(result)
        return result

    def graph_visualization_tool(self, query: str, table_names: list[str]) -> str:
        """
        Acts as a proxy to the GraphVisualization agent.
        It receives a natural language visualization request and table_name from metadata
        and returns a message indicating that the visualization image was created.

        Parameters:
            query (str): A natural language visualization request with a context and explanation.
            table_names (list[str]): A list of table names what will be used for this query.

        Returns:
            str: A message indicating that the visualization image was created or an error message.
        """
        print("visualization_tool", query, table_names)
        metadata = self.metadata.model_copy(deep=True)
        try:
            img, raw = self.visu.invoke(query, metadata.filter_tables(table_names))
        except Exception as e:
            traceback.print_exc()
            return json.dumps({"error": str(e)})
        self.visu.save_base64_image()
        self.base64_image = img
        result = []
        for r in raw:
            result.append(r.model_dump_json(indent=4))
        print(result)
        return f"Visualization Generated successfully. {img[:50]} DB result {result}"

    def orchestrator_node(self, state: ChatOrchestratorState):
        """Main orchestrator node that processes user input and coordinates tool usage."""
        return {"messages": [self.llm.invoke(state["messages"])]}

    def compile(self):
        """Compile the orchestrator graph with tool integration."""
        builder = StateGraph(ChatOrchestratorState)
        builder.add_node("orchestrator", self.orchestrator_node)
        builder.add_node("tools", self.tool_node)

        builder.set_entry_point("orchestrator")
        builder.add_edge("tools", "orchestrator")
        builder.add_conditional_edges("orchestrator", tools_condition)

        # Compile the graph
        self.graph = builder.compile()

    def invoke(self, prompt: str) -> str:
        """Invoke the orchestrator with a user prompt."""
        sys_prompt = make_sys_prompt_orch(self.metadata)
        reply = self.graph.invoke({"messages": [sys_prompt, HumanMessage(prompt)]})
        result = (
            reply["messages"][-1].content
            if reply["messages"][-1].content is not None
            else ""
        )
        return result


if __name__ == "__main__":

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    example_metadata_path = repo_root / "db_faker" / "data" / "metadata_dump.json"
    if not example_metadata_path.exists():
        raise FileNotFoundError(
            f"Example metadata file not found: {example_metadata_path}"
        )

    with example_metadata_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    example_metadata = SchemaMetadata.model_validate(data)
    make_sys_prompt_orch(example_metadata)
    client = PostgresClient()
    client.connect()
    agent = ChatOrchestrator(db_client=client, metadata=example_metadata)
    print(agent.invoke("How may calls we had in per month show me"))
