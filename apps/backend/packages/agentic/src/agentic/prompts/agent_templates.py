import os
from langchain.prompts import PromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from common.utils import load_system_message
from common.models.db_metadata import SchemaMetadata, TableMetadata


# -------------------------------- Load System Messages ---------------------------------

base_dir = os.path.dirname(os.path.abspath(__file__))
sys_data = load_system_message(base_dir)


def make_sys_prompt_orch(metadata: SchemaMetadata) -> SystemMessage:
    """Generate the system prompt for the Chat Orchestrator agent."""
    simple_metadata = metadata.simplify().model_dump_json(indent=4)
    prompt = PromptTemplate(
        input_variables=["metadata"],
        template=sys_data["orchestrator"],
    )
    return SystemMessage(prompt.format(metadata=simple_metadata))


def make_sys_prompt_text_to_sql(
    metadata: SchemaMetadata, db_type: str
) -> SystemMessage:
    """Generate the system prompt for the Text to SQL agent."""
    prompt = PromptTemplate(
        input_variables=["metadata", "db_type"],
        template=sys_data["text_to_sql"],
    )
    return SystemMessage(
        prompt.format(metadata=metadata.model_dump_json(indent=4), db_type=db_type)
    )


def make_txt2sql_exec_sql(
    sql: str, exception_message: str, db_type: str
) -> HumanMessage:
    """Generate the system prompt for the Text to SQL Execution agent."""
    prompt = PromptTemplate(
        template=f"""
            Exception occurred while trying to run query {sql} exception {exception_message}
            Data base Information: - Database Type = {db_type}
        """,
    )
    return HumanMessage(prompt.format())


def make_txt2sql_exec_format(llm_output: str, exception_message: str) -> HumanMessage:
    """Generate the system prompt for the Text to SQL Execution agent."""
    prompt = PromptTemplate(
        template=f"Exception occurred while trying to convert {llm_output} to Json.loads {exception_message}",
    )
    return HumanMessage(prompt.format())


def make_sys_prompt_relation_mapper(metadata: TableMetadata) -> HumanMessage:
    """Generate the system prompt for the Relation Mapper agent."""
    prompt = PromptTemplate(
        input_variables=["metadata"],
        template=sys_data["relation_mapper"],
    )
    return HumanMessage(prompt.format(metadata=metadata.model_dump_json(indent=4)))


def make_sys_prompt_insight_generator(
    metadata: TableMetadata, gen_limit: int = 8
) -> HumanMessage:
    """Generate the system prompt for the Insight Generator agent."""
    prompt = PromptTemplate(
        input_variables=["metadata", "gen_limit"],
        template=sys_data["insight_generator"],
    )
    return HumanMessage(
        prompt.format(
            metadata=metadata.model_dump_json(indent=4),
            gen_insight_limit=gen_limit,
        )
    )


def make_system_prompt_visualization(metadata: SchemaMetadata):
    """Generate the system prompt for the visualization Generator agent."""
    prompt = PromptTemplate(
        input_variables=["metadata"],
        template=sys_data["graph_visualization"],
    )
    return HumanMessage(
        prompt.format(
            metadata=metadata.model_dump_json(indent=4),
        )
    )
