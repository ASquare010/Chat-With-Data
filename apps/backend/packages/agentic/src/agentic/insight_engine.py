import json
from typing import Dict
from pydantic import ValidationError
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from common.models.db_metadata import (
    SchemaMetadata,
    RelationMetadata,
    InsightCloudMetadata,
)
from agentic.prompts.agent_templates import (
    make_sys_prompt_relation_mapper,
    make_sys_prompt_insight_generator,
)


# ----------------------------------------- Agents --------------------------------------


class InsightGenerator:
    """
    Insight Generator Agent that maps relations for each table in the schema
    using a language model (LLM). It processes each table's metadata and updates
    the relations based on the LLM's output.
    """

    def __init__(self, metadata: SchemaMetadata, db_type: str = "postgres:18"):
        self.llm = ChatOpenAI(
            model="gpt-5",
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.metadata = metadata
        self.db_type = db_type
        self.loop_count = 0
        self.compile()

    def relation_mapper_node(self, metadata: SchemaMetadata):
        """
        Map relations for each table using LLM output.
        The LLM should return a JSON matching RelationMetadata schema.
        """
        for table_name, table_metadata in metadata.entities.items():
            if table_metadata.relations:
                print(
                    f"{table_name}: Already has relations = {len(table_metadata.relations)}"
                )
                continue
            sys_prompt = make_sys_prompt_relation_mapper(table_metadata)
            print(f"[relation_mapper_node] Processing table: {table_name}")
            raw = self.llm.invoke([sys_prompt])
            try:
                data = json.loads(raw.content)
                relations: Dict[str, RelationMetadata] = {
                    rel_name: RelationMetadata(**rel_data)
                    for rel_name, rel_data in data.items()
                }
                table_metadata.relations = relations

            except (json.JSONDecodeError, ValidationError) as e:
                print(
                    f"[relation_mapper_node] Error processing table '{table_name}': {e}"
                )
                table_metadata.relations = {}

        return metadata

    def insight_generator_node(self, metadata: SchemaMetadata):
        """
        Generate insights for each table in the schema using the LLM output.
        Populates the `insights` field in each TableMetadata.
        """
        for table_name, table_metadata in metadata.entities.items():
            if table_metadata.insights:
                print(
                    f"{table_name} Already has Insights = {len(table_metadata.insights)}"
                )
                continue
            print(f"\n🧩 Processing table: {table_name}")
            sys_prompt = make_sys_prompt_insight_generator(table_metadata, gen_limit=8)
            raw = self.llm.invoke([sys_prompt])
            try:
                insights_json = json.loads(raw.content)
                parsed_insights = {
                    insight_name: InsightCloudMetadata(**insight_data)
                    for insight_name, insight_data in insights_json.items()
                }

                table_metadata.insights = parsed_insights

                print(
                    f"✅ {table_name}: {len(parsed_insights)} insights generated successfully."
                )

            except Exception as e:
                print(f"⚠️ Failed to process insights for table {table_name}: {e}")
        return metadata

    def check_hypothesis_node(self, metadata: SchemaMetadata):
        """
        Check hypotheses for each table in the schema using the LLM output.
        Populates the `hypotheses` field in each TableMetadata.
        """
        for table_name, table_metadata in metadata.entities.items():
            if table_metadata.insights:
                print(
                    f"{table_name} Already has Insights = {len(table_metadata.insights)}"
                )
                continue
            print(f"\n🧩 Processing table: {table_name}")
            sys_prompt = make_sys_prompt_insight_generator(table_metadata, gen_limit=8)
            raw = self.llm.invoke([sys_prompt])
            try:
                insights_json = json.loads(raw.content)
                parsed_insights = {
                    insight_name: InsightCloudMetadata(**insight_data)
                    for insight_name, insight_data in insights_json.items()
                }

                table_metadata.insights = parsed_insights

                print(
                    f"✅ {table_name}: {len(parsed_insights)} insights generated successfully."
                )

            except Exception as e:
                print(f"⚠️ Failed to process insights for table {table_name}: {e}")
        return metadata

    def compile(self):

        builder = StateGraph(SchemaMetadata)
        builder.add_node("relation_mapper", self.relation_mapper_node)
        builder.add_node("insight_generator", self.insight_generator_node)

        # Regular flow
        builder.set_entry_point("relation_mapper")
        builder.add_edge("relation_mapper", "insight_generator")
        builder.add_edge("insight_generator", END)

        # Compile the graph
        self.graph = builder.compile()

    def invoke(self):
        return self.graph.invoke(self.metadata)


if __name__ == "__main__":

    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[3]

    example_metadata_path = (
        repo_root / "db_faker" / "data" / "metadata_with_insights.json"
    )

    if not example_metadata_path.exists():
        raise FileNotFoundError(
            f"Example metadata file not found: {example_metadata_path}"
        )

    with example_metadata_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    example_metadata = SchemaMetadata.model_validate(data)
    engine = InsightGenerator(example_metadata)
    result = engine.invoke()

    output_path = Path("metadata.json")
    # Serialize to JSON string
    json_data = engine.metadata.model_dump_json(indent=4)

    # Write to file
    output_path.write_text(json_data, encoding="utf-8")

    print(f"✅ Metadata saved to {output_path}")
