import sqlite3, json
from src.utils import *
from typing import Literal
from src.agent_states import *
from langchain_openai import ChatOpenAI
from IPython.display import Image, display
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


# -------------------------------- Load System Messages ---------------------------------

sys_data = load_system_message()

# ----------------------------------------- Agents --------------------------------------

class Text2SQL_Agent():
    
    def __init__(self,prompt:str, system_prompt:str, db_name:str="data/data.db",table_name:str="data", database_type:str="SQLite",max_try:int=2):
        self.llm  = ChatOpenAI(model="gpt-4o", model_kwargs={ "response_format": { "type": "json_object" } })
        self.prompt = prompt
        self.db_name = db_name
        self.max_try = max_try
        self.table_name = table_name
        self.database_type = database_type
        self.system_prompt = system_prompt
        self.run_failed = False
        self.loop_count = 0

        self.compile()

    def text_to_sql_node(self, state: Text2SQLState):
        
        self.loop_count += 1

        if state.get("loop_again", True):
            sys_prompt = SystemMessage(self.system_prompt + f"\n- Table_name={self.table_name}\n- database_type={self.database_type}")
            issue_prompt = HumanMessage(f"Exception has {state.get('exception_message', '')} {self.prompt}")

            result = self.llm.invoke([sys_prompt] + state["messages"] + [issue_prompt] )
        else:
            sys_prompt = SystemMessage(sys_data["text_to_sql"] + f"\n- Table_name={self.table_name}\n- database_type={self.database_type}")
            result = self.llm.invoke([sys_prompt] + state["messages"])

        if self.loop_count > self.max_try:
            self.run_failed = True   

        return {"messages": [result], "sql_queries": result.content, "loop_again": False}
    
    def execute_sql_node(self, state: Text2SQLState):
        current_sql_query = ""
        result = list()
        try:
            sql_queries = json.loads(state["sql_queries"] if hasattr(state["sql_queries"], "sql") else str(state["sql_queries"]))
            
            try:
                for sql_query in sql_queries["sql"]:
                    current_sql_query = sql_query
                    db_result = self.run_sql_query(sql_query)
                    result.append({ "sql_query": current_sql_query, "db_result": db_result})
                
                return {"loop_again": False, "result_data": result}
            
            except Exception as e:
                exception_message = f"""
                    Exception occurred while trying to run query {current_sql_query} exception {str(e)}
                    Data base Information: - Database Type = {self.database_type} - Table_name = {self.table_name}\n
                """
                print(exception_message)
                return {"loop_again": True, "exception_message": exception_message}

            
        except Exception as e:
            exception_message = f"Exception occurred while trying to convert {state["sql_queries"]} to Json.loads {str(e)}"
            print(exception_message)
            return {"loop_again": True, "exception_message": exception_message}
        
    def run_sql_query(self, query):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        return result

    def loop_again_condition(self,state: Text2SQLState)-> Literal["text_to_sql", END]:
        return "text_to_sql" if state.get("loop_again", False) else END
    
    def compile(self):
        builder = StateGraph(Text2SQLState)
        builder.add_node("text_to_sql", self.text_to_sql_node)
        builder.add_node("execute_sql", self.execute_sql_node)

        # Regular flow
        builder.add_edge(START, "text_to_sql")
        builder.add_edge("text_to_sql", "execute_sql")
        builder.add_conditional_edges("execute_sql", self.loop_again_condition)
        
        # Compile the graph
        self.graph = builder.compile()

    def print_graph(self):
        try:
            png_data = self.graph.get_graph(xray=True).draw_mermaid_png()
            display(Image(png_data))
        except Exception as e:
            print("Failed to render graph image:", e)
            print(self.graph.get_graph(xray=True).draw_mermaid())

    def invoke(self):
        return self.graph.invoke({"messages": [HumanMessage(self.prompt)], "loop_again": False})
    

class InsightGenerator():
    
    def __init__(self,metadata:str):
        self.llm  = ChatOpenAI(model="gpt-4o", model_kwargs={ "response_format": { "type": "json_object" } })
        self.metadata = metadata
        self.loop_count = 0
        self.compile()

    def metadata_node(self, state: InsightState):
        sys_prompt = SystemMessage(sys_data["metadata"])
        return {"messages": [self.llm.invoke([sys_prompt] + state["messages"])]}
    
    def relation_mapper_node(self, state: InsightState):
        sys_prompt = SystemMessage(sys_data["relation_mapper"])
        return {"messages": [self.llm.invoke([sys_prompt] + state["messages"])]}
    
    def insight_generator_node(self, state: InsightState):
        self.loop_count += 1

        if state.get("loop_again", False):
            sys_prompt = SystemMessage(sys_data["insight_generator"])
            insights = self.llm.invoke([sys_prompt] + state["messages"])
        else:
            sys_prompt = SystemMessage(sys_data["insight_generator"])
            issue_prompt = HumanMessage(f"Correct the insight json generated {state.get('insights', '')} exception {state.get('exception_message', '')}")
            insights = self.llm.invoke([sys_prompt] + state["messages"]+ [issue_prompt])

        if self.loop_count > 2:
            raise Exception("Loop count exceeded")

        return {"messages": [insights], "insights": insights.content, "loop_again": False}

    def check_json_syntax_node(self, state: InsightState):
        try:
            json.loads(state["insights"])
            return {"loop_again": False}
        except Exception as e:
            error = f"Expected JSON syntax error {e}"
            print(error)
            return {"loop_again": True, "exception_message": error}
        
    def make_insight_cloud_node(self, state: InsightState):
        insights = json.loads(state["insights"])
        keys_to_remove = []
        i = 0
        for insight_name, insight_data in insights.items():
            print("Processing insight -> ** ",insight_name," **", i)
            i += 1
            t2s = Text2SQL_Agent(str({insight_name: insight_data}), sys_data["text_to_sql"])
            t2s_result = t2s.invoke()
            if t2s.run_failed:
                print("Removed insight -> ** ",insight_name," **")
                keys_to_remove.append(insight_name)
                continue
            insight_data["sql_results_pair"] = t2s_result["result_data"]
            insight_summary = self.llm.invoke([sys_data["summarizer"]] + state["messages"]+ [HumanMessage(f"The insight {insight_name} {insight_data}")])
            insight_data["insight_summary"] = insight_summary.content
            insights[insight_name] = insight_data
        
        # Remove the marked keys after the iteration is complete ---
        for key in keys_to_remove:
            del insights[key]
        
        return {"json_insights": insights}
      
    def loop_again_condition(self,state: Text2SQLState)-> Literal["insight_generator", "make_insight_cloud"]:
        return "insight_generator" if state.get("loop_again", False) else "make_insight_cloud"

    def compile(self):
        builder = StateGraph(InsightState)
        builder.add_node("metadata", self.metadata_node)
        builder.add_node("relation_mapper", self.relation_mapper_node)
        builder.add_node("insight_generator", self.insight_generator_node)
        builder.add_node("check_json_syntax", self.check_json_syntax_node)
        builder.add_node("make_insight_cloud", self.make_insight_cloud_node)

        # Regular flow
        builder.add_edge(START, "metadata")
        builder.add_edge("metadata", "relation_mapper")
        builder.add_edge("relation_mapper", "insight_generator")
        builder.add_edge("insight_generator", "check_json_syntax")
        builder.add_conditional_edges("check_json_syntax", self.loop_again_condition)
        builder.add_edge("make_insight_cloud", END)
        
        
        # Compile the graph
        self.graph = builder.compile()

    def print_graph(self):
        try:
            png_data = self.graph.get_graph(xray=True).draw_mermaid_png()
            display(Image(png_data))
        except Exception as e:
            print("Failed to render graph image:", e)
            print(self.graph.get_graph(xray=True).draw_mermaid())

    def invoke(self):
        return self.graph.invoke({"messages": [HumanMessage(self.metadata)]})
    

class GraphVisualization():
    
    def __init__(self, user_prompt: str, metadata: str,table_name:str="data",database_type:str="SQLite" ,database_name:str="data/data.db"):

        tools = [self.text_to_sql_tool, self.py_code_tool]
        self.llm = ChatOpenAI(model="gpt-4o").bind_tools(tools)
        self.tool_node = ToolNode(tools=tools)
        self.prompt = user_prompt
        self.metadata = metadata
        self.db_name = database_name
        self.table_name = table_name
        self.database_type = database_type
        self.database_results = []
        self.compile()
    
    def make_system_prompt(self):
        return SystemMessage(
            sys_data["chart_display"] +
            f"\n- Metadata = {self.metadata},\n **database_type** = {self.database_type}, \n**table_name** = {self.table_name}"
        )
    
    def run_sql_query(self, query):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        return result
    
    def text_to_sql_tool(self, query: str):
        """
        Provided a SQL query, returns the result of the query.

        Parameters:
            query (str): A Runnable SQL query.

        Returns:
            result from database
        """
        try:
            self.database_results = self.run_sql_query(query)
            return self.database_results[:5]
        except Exception as e:
            return "Exception in text_to_sql_tool ->",e    
    
    def py_code_tool(self,code_string: str,execution_globals: dict = None) -> str:
        """
        Executes Python code provided as a string and returns the value of 'base64_image'.
        The variable 'result_data' (containing results from the database) is injected into the execution namespace.
        """
        namespace = {}
        if execution_globals:
            namespace.update(execution_globals)

        if self.database_results is not None:
            namespace['result_data'] = self.database_results
        else:
            namespace['result_data'] = []
            print("Warning: self.database_results not set before calling py_code_tool.")


        try:
            exec("import matplotlib.pyplot as plt", namespace, namespace)
            exec("import pandas as pd", namespace, namespace)
            exec("import io", namespace, namespace)
            exec("import base64", namespace, namespace)
            exec(code_string, namespace, namespace)
            try:
                if 'plt' in namespace:
                    namespace['plt'].close('all')
            except Exception:
                pass # Ignore errors during cleanup

            result = namespace.get('base64_image')

            if result is not None and isinstance(result, str):
                self.base64_image = result
                return "image created successfully -> "+result[:30]
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
            error_details = f"Error during Python code execution: {type(e).__name__}: {e}\n"
            error_details += f"Data available in 'result_data': {namespace.get('result_data', 'Not Set')}\n"
            error_details += f"Traceback:\n{tb_str}"
            return error_details
        
    def chart_display_node(self, state: GraphVisualizationState):
        sys_prompt = self.make_system_prompt()
        return {"messages": [self.llm.invoke([sys_prompt] + state["messages"])]}
    
    def compile(self):
        builder = StateGraph(GraphVisualizationState)
        builder.add_node("chart_display", self.chart_display_node)
        builder.add_node("tools", self.tool_node)

        builder.add_edge(START, "chart_display")
        builder.add_edge("tools", "chart_display")
        builder.add_conditional_edges("chart_display", tools_condition)
        
        # Compile the graph
        self.graph = builder.compile()

    def print_base64_image(self):
        try:
            png_data = base64.b64decode(self.base64_image)
            display(Image(data=png_data))
        except Exception as e:
            print("Failed to render base64 image:", e)

    def print_graph(self):
        try:
            png_data = self.graph.get_graph(xray=True).draw_mermaid_png()
            display(Image(png_data))
        except Exception as e:
            print("Failed to render graph image:", e)
            print(self.graph.get_graph(xray=True).draw_mermaid())

    def invoke(self):
        return self.graph.invoke({"messages": [HumanMessage(self.prompt)]})


class ChatOrchestrator():
    
    def __init__(self,metadata: str, insight: dict):

        tools = [self.text_to_sql_tool, self.search_web_tool,self.graph_visualization_tool]
        self.llm = ChatOpenAI(model="gpt-4o").bind_tools(tools)
        self.tool_node = ToolNode(tools=tools)
        self.metadata = metadata
        self.insight = insight
        self.base64_image = ""
        self.compile()
    
    def make_system_prompt(self):
        return SystemMessage(
            sys_data["orchestrator"] +
            f"\n- Metadata = {self.metadata}" +
            f"\n- Insight = {self.insight}"
        )
    
    def text_to_sql_tool(self, query: str) -> list:
        """
        Converts natural language text to SQL queries.

        Parameters:
            query (str): The natural language description for the desired SQL query.

        Returns:
            list: A list of generated SQL query strings and their corresponding results.
        """
        txt2sql_agent = Text2SQL_Agent(query, sys_data["text_to_sql"]).invoke()
        return txt2sql_agent.get("result_data", [])
    
    def search_web_tool(self, query: str) -> list:
        """
        Searches the web using the TAVILY.

        Parameters:
            query (str): The search query string.

        Returns:
            list: The search results from the TAVILY-powered web search.
        """

        tavily = TavilySearchResults(max_results=3) 
        return tavily(query)
    
    def graph_visualization_tool(self, query: str) -> str:
        """
        Acts as a proxy to the GraphVisualization agent.
        It receives a natural language visualization request
        and returns a message indicating that the visualization image was created.

        Parameters:
            query (str): A natural language visualization request with a context and explanation.

        Returns:
            str: A message indicating that the visualization image was created or an error message.
        """
        visu = GraphVisualization(query, self.metadata)
        visu.invoke()
        self.base64_image = visu.base64_image
        return f"Visualization tool invoked. {self.base64_image[:50]}"
    
    def orchestrator_node(self, state: ChatOrchestratorState):
        sys_prompt = self.make_system_prompt()
        response = self.llm.invoke([sys_prompt] + state["messages"]).content
        return {"messages": [AIMessage(content=response)]}
    
    def compile(self):
        builder = StateGraph(ChatOrchestratorState)
        builder.add_node("orchestrator", self.orchestrator_node)
        builder.add_node("tools", self.tool_node)

        builder.add_edge(START, "orchestrator")
        builder.add_edge("tools", "orchestrator")
        builder.add_conditional_edges("orchestrator", tools_condition)
        
        # Compile the graph
        self.graph = builder.compile()
    
    def print_base64_image(self):
        try:
            png_data = base64.b64decode(self.base64_image)
            display(Image(data=png_data))
        except Exception as e:
            print("Failed to render base64 image:", e)

    def print_graph(self):
        try:
            png_data = self.graph.get_graph(xray=True).draw_mermaid_png()
            display(Image(png_data))
        except Exception as e:
            print("Failed to render graph image:", e)
            print(self.graph.get_graph(xray=True).draw_mermaid())

    def invoke(self, prompt:str):
        self.prompt = prompt
        reply = self.graph.invoke({"messages": [HumanMessage(prompt)]})
        result = reply["messages"][-1].content
        img = self.base64_image
        self.base64_image = ""
        return result, img, reply
