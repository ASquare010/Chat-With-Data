import json
import base64
from pathlib import Path
from typing import List, Optional, Tuple
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage
from agentic.prompts.agent_templates import make_system_prompt_visualization
from agentic.agent_states import GraphVisualizationState
from agentic.text_to_sql import Text2SQLAgent
from common.utils.postgres_client import PostgresClient
from common.models.db_metadata import SchemaMetadata, DatabaseResult
from common.config.settings import settings


class GraphVisualization:
    """Agent to visualize data using SQL and Python code execution."""

    def __init__(
        self,
        db_client: PostgresClient,
        metadata: SchemaMetadata,
        database_type: str = "postgres:18",
    ):

        tools = [self.text_to_sql_tool, self.py_code_tool]
        self.llm = ChatOpenAI(model=settings.COMMON_MODEL).bind_tools(tools)
        self.tool_node = ToolNode(tools=tools)
        self.database_type = database_type
        self.db_client = db_client
        self.metadata = metadata
        self.base64_image: str = ""
        self.database_results: List[DatabaseResult] = []
        self.compile()

    def text_to_sql_tool(self, query: str) -> str:
        """
        Provided a SQL query, returns the result of the query.

        Parameters:
            query (str): A Runnable SQL query.

        Returns:
            result from database
        """
        try:
            text2sql_agent = Text2SQLAgent(
                self.db_client,
                self.metadata,
                self.database_type,
            )
            text2sql_agent.invoke(user_prompt=query)
            raw_results = text2sql_agent.invoke(user_prompt=query)
            self.database_results = DatabaseResult.normalize_list(raw_results)
            output = ""
            for res in self.database_results:
                output += f"{res.model_dump_json(indent=4)[:500]}....,\n"
            return f"[{output}] data is injected in variable `result_data`"
        except Exception as e:
            print("Exception in text_to_sql_tool ->", e)
            return "Exception in text_to_sql_tool ->", e

    def py_code_tool(self, code_string: str, execution_globals: dict = None) -> str:
        """
        Executes Python code provided as a string and returns the value of 'base64_image'.
        The variable 'result_data' (containing results from the database) is injected into the execution namespace.
        """
        namespace = {}
        if execution_globals:
            namespace.update(execution_globals)

        if self.database_results is not None:
            namespace["result_data"] = self.database_results
        else:
            namespace["result_data"] = []
            print("Warning: self.database_results not set before calling py_code_tool.")

        try:
            exec(
                "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt",
                namespace,
                namespace,
            )
            exec("import pandas as pd", namespace, namespace)
            exec("import io", namespace, namespace)
            exec("import base64", namespace, namespace)
            exec(code_string, namespace, namespace)
            try:
                if "plt" in namespace:
                    namespace["plt"].close("all")
            except Exception:
                pass  # Ignore cleanup errors
            try:
                if "plt" in namespace:
                    namespace["plt"].close("all")
            except Exception:
                pass  # Ignore errors during cleanup

            result = namespace.get("base64_image")

            if result is not None and isinstance(result, str):
                self.base64_image = result
                return "image created successfully -> " + result[:30]
            elif result is None:
                return "Error: Python code executed successfully, but the required 'base64_image' variable was not set or was None."
            else:
                return f"Error: Python code executed, 'base64_image' was set, but it is not a string (type: {type(result)}). It must be a base64 encoded string."

        except NameError as e:
            return f"Error during Python code execution (NameError): {e}. Ensure the code accesses data via the 'result_data' variable (list of dicts) and imports necessary libraries (pandas, matplotlib, etc.)."
        except ImportError as e:
            return f"Error during Python code execution (ImportError): {e}. Ensure the Python code includes all necessary imports (e.g., pandas, matplotlib.pyplot, seaborn, base64, io)."
        except Exception as e:
            import traceback

            tb_str = traceback.format_exc()
            error_details = (
                f"Error during Python code execution: {type(e).__name__}: {e}\n"
            )
            error_details += f"Data available in 'result_data': {namespace.get('result_data', 'Not Set')}\n"
            error_details += f"Traceback:\n{tb_str}"
            return error_details

    def chart_display_node(self, state: GraphVisualizationState):
        """Call LLM for visualization"""
        return {"messages": [self.llm.invoke(state["messages"])]}

    def compile(self):
        """Compile graph builder.compile"""
        builder = StateGraph(GraphVisualizationState)
        builder.add_node("chart_display", self.chart_display_node)
        builder.add_node("tools", self.tool_node)

        builder.set_entry_point("chart_display")
        builder.add_edge("tools", "chart_display")
        builder.add_conditional_edges("chart_display", tools_condition)

        # Compile the graph
        self.graph = builder.compile()

    def save_base64_image(self, filename: str = "chart_output.png"):
        """Decode and save the generated base64 image to disk safely."""
        try:
            if not hasattr(self, "base64_image") or not self.base64_image:
                print("❌ No image found in `self.base64_image`.")
                return
            png_data = base64.b64decode(self.base64_image)
            output_dir = Path("outputs")
            output_dir.mkdir(exist_ok=True)
            filepath = output_dir / filename
            with open(filepath, "wb") as f:
                f.write(png_data)

            print(f"✅ Saved chart image to: {filepath.resolve()}")
        except Exception as e:
            print(f"❌ Failed to save image: {e}")

    def invoke(
        self, user_prompt: str, metadata: Optional[SchemaMetadata] = None
    ) -> Tuple[str, List[DatabaseResult]]:
        """Entery point"""
        self.base64_image = ""
        self.database_results = []
        sys_prompt = make_system_prompt_visualization(
            (metadata if metadata else self.metadata),
        )
        self.graph.invoke({"messages": [sys_prompt, HumanMessage(user_prompt)]})
        return self.base64_image if self.base64_image else "", self.database_results


if __name__ == "__main__":

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

    engine = GraphVisualization(client, example_metadata)
    img, result = engine.invoke("make me a simple bar chat of this call per day")
    engine.save_base64_image()
