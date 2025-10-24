# apps/backend/packages/db_faker/src/db_faker/main.py
import os
import re
import json
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from common.utils.postgres_client import PostgresClient
from common.models.db_metadata import SchemaMetadata, TableMetadata


class PushDataToPostgres:
    """
    Reads schema metadata JSON (clickhouse-like types, possibly wrapped in Nullable(...))
    and creates schema + tables in Postgres using PostgresClient.

    Usage:
        pusher = PushDataToPostgres()
        pusher.invoke(metadata_path)
    """

    def __init__(self, pg_client: Optional[PostgresClient] = None):
        if not pg_client:
            client = PostgresClient()
            client.connect_pool(minconn=1, maxconn=5)
            client.test_connection()
        self.client = client or pg_client

    # -----------------------
    # Type helpers
    # -----------------------
    @staticmethod
    def _extract_nullable(ch_type: str) -> Tuple[str, bool]:
        """
        Extract inner type and nullable flag.

        Examples:
            "Nullable(String)" -> ("String", True)
            "DateTime64(9)"    -> ("DateTime64(9)", False)
        """
        if not ch_type or not isinstance(ch_type, str):
            return "String", True

        ch_type = ch_type.strip()
        m = re.match(r"^\s*Nullable\s*\(\s*(.+)\s*\)\s*$", ch_type, flags=re.IGNORECASE)
        if m:
            inner = m.group(1).strip()
            return inner, True
        return ch_type, False

    @staticmethod
    def _map_type_to_pg(ch_type: str, col_name: Optional[str] = None) -> str:
        """
        Map a (possibly inner) ClickHouse-like type to PostgreSQL type.
        Heuristics implemented for the types present in your metadata.
        """
        if not ch_type:
            return "TEXT"

        t = ch_type.strip()

        # normalize to lower for checks but keep parentheses for precision parsing
        tl = t.lower()

        # String types
        if tl.startswith("string") or tl.startswith("varchar") or tl == "text":
            return "TEXT"

        # Date/time types, handle DateTime64(9) etc.
        m_dt = re.match(r"datetime(?:64)?\s*(?:\(\s*(\d+)\s*\))?", tl)
        if m_dt:
            precision = m_dt.group(1)
            if precision:
                try:
                    p = int(precision)
                    # Postgres TIMESTAMP supports precision (0-6 typically). We'll clamp to 6.
                    p_clamped = min(max(p, 0), 6)
                    return f"TIMESTAMP({p_clamped})"
                except Exception:
                    return "TIMESTAMP"
            return "TIMESTAMP"

        if tl.startswith("date"):
            return "DATE"

        # Unsigned ints / ints
        if tl.startswith("uint64") or tl == "uint64" or tl == "ulong" or "uint64" in tl:
            return "BIGINT"
        if tl.startswith("uint32") or "uint32" in tl or tl == "uint":
            return "INTEGER"
        if tl.startswith("uint16"):
            return "SMALLINT"
        if tl.startswith("uint8"):
            # for boolean-like columns use BOOLEAN when column name suggests it
            if col_name and (
                col_name.startswith("is_")
                or col_name.startswith("has_")
                or col_name == "is_current"
            ):
                return "BOOLEAN"
            return "SMALLINT"

        if tl.startswith("int64") or "int64" in tl:
            return "BIGINT"
        if tl.startswith("int32") or "int32" in tl:
            return "INTEGER"
        if tl.startswith("int") and "int" == tl:
            return "INTEGER"

        # floats / doubles
        if tl.startswith("float64") or "double" in tl:
            return "DOUBLE PRECISION"
        if tl.startswith("float") or "float32" in tl:
            return "REAL"

        # decimals / numerics
        if tl.startswith("decimal") or tl.startswith("numeric"):
            # keep as NUMERIC (could parse precision/scale if present)
            return "NUMERIC"

        # boolean textual representations
        if tl in ("boolean", "bool"):
            return "BOOLEAN"

        # fallback: TEXT
        return "TEXT"

    # -----------------------
    # DDL helpers
    # -----------------------
    def create_schema_if_not_exists(self, schema_name: str) -> None:
        """
        Create schema if not exists using psycopg2.sql identifiers.
        """
        if not schema_name:
            raise ValueError("schema_name is required")

        if not self.client.conn or getattr(self.client.conn, "closed", 1):
            self.client.connect()

        q = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
            sql.Identifier(schema_name)
        )
        # PostgresClient.execute can accept sql.Composed
        self.client.execute(q)

    def create_table_from_meta(
        self, schema_name: str, table_meta: Dict[str, Any]
    ) -> None:
        """
        Create a single table from a table_meta dictionary.
        table_meta expected shape:
          {"table_name": "calls", "fields": { "col": {"data_type": "Nullable(String)", "description": "..."} , ... } }
        """
        if not self.client.conn or getattr(self.client.conn, "closed", 1):
            self.client.connect()

        table_name = table_meta.get("table_name") or table_meta.get("name")
        if not table_name:
            raise ValueError("table_meta must include 'table_name'")

        fields = table_meta.get("fields", {})
        if not fields:
            # nothing to create
            print(f"[PushDataToPostgres] No fields for table {table_name}, skipping.")
            return

        col_fragments = []
        for col_name, col_meta in fields.items():
            ch_type = col_meta.get("data_type", "String")
            inner, nullable = self._extract_nullable(ch_type)
            pg_type = self._map_type_to_pg(inner, col_name)
            # decide NOT NULL: if not nullable -> treat as NOT NULL, else leave as nullable
            not_null_sql = sql.SQL("NOT NULL") if not nullable else sql.SQL("")
            col_def = sql.SQL("{} {} {}").format(
                sql.Identifier(col_name),
                sql.SQL(pg_type),
                not_null_sql,
            )
            col_fragments.append(col_def)

        # join columns
        cols_sql = sql.SQL(", ").join(col_fragments)

        create_stmt = sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            cols_sql,
        )

        # execute
        self.client.execute(create_stmt)
        print(
            f"[PushDataToPostgres] Created or verified table {schema_name}.{table_name}"
        )

        # Optionally add column comments (descriptions)
        # We'll add COMMENT ON COLUMN for any field that has a non-empty description
        for col_name, col_meta in fields.items():
            desc = col_meta.get("description") or ""
            if desc:
                comment_q = sql.SQL("COMMENT ON COLUMN {}.{}.{} IS %s").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.Identifier(col_name),
                )
                # Use client.cur.execute with params via client.execute
                self.client.execute(comment_q, (desc,))

    # -----------------------
    # Main: load metadata + create schema/tables
    # -----------------------
    def load_metadata_from_file(self, file_path: str) -> SchemaMetadata:
        """
        Load metadata JSON from file. If top-level is a list, take the first element.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Metadata file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, list):
            if not payload:
                raise ValueError("Metadata JSON list is empty")
            payload = payload[0]
        return SchemaMetadata(**payload)

    def create_schema_and_tables(self, metadata_file: str) -> str:
        """
        Main method to create schema and tables from metadata file.
        """
        if not metadata_file:
            raise FileNotFoundError(
                "Could not find metadata_dump.json in expected places; pass explicit path"
            )

        # read metadata
        metadata: SchemaMetadata = self.load_metadata_from_file(metadata_file)
        schema_name = metadata.schema_name
        entities = metadata.entities

        # connect & apply
        try:
            self.client.connect_pool(minconn=1, maxconn=5)
            if schema_name:
                self.create_schema_if_not_exists(schema_name)
            else:
                raise ValueError("metadata must include schema_name")

            for ent_name, table_meta in entities.items():
                if isinstance(table_meta, TableMetadata):
                    table_name = table_meta.table_name or ent_name
                    table_meta_dict = table_meta.dict()
                    table_meta_dict["table_name"] = table_name
                else:
                    raise ValueError(
                        f"entity {ent_name} metadata is not a TableMetadata object"
                    )

                self.create_table_from_meta(schema_name, table_meta_dict)

            print("[PushDataToPostgres] All tables created/verified.")
        except Exception as exc:
            print(f"[PushDataToPostgres] Failed to create schema/tables: {exc}")
            raise

        return schema_name

    def load_data_into_tables(self, tables_paths: list[str], schema_name: str) -> None:
        """
        Load CSV files into Postgres tables using pandas.
        Each CSV file should have the same name as the table (without .csv).
        """
        if not tables_paths:
            print("[PushDataToPostgres] No CSV files provided for data load.")
            return

        if not self.client.conn or getattr(self.client.conn, "closed", 1):
            self.client.connect()

        if not schema_name:
            raise RuntimeError("Schema name is not set in the Postgres client")

        for csv_file in tables_paths:
            if not Path(csv_file).exists():
                print(f"[PushDataToPostgres] CSV file not found: {csv_file}, skipping.")
                continue

            table_name = Path(csv_file).stem

            print(
                f"[PushDataToPostgres] Loading data from {csv_file} into {schema_name}.{table_name}..."
            )
            try:
                df = pd.read_csv(
                    csv_file,
                    low_memory=False,
                    keep_default_na=True,
                    na_values=["NaT", "NaN", ""],
                )

                if df.empty:
                    print(f"[PushDataToPostgres] CSV {csv_file} is empty, skipping.")
                    continue

                # Convert NaN to None
                df = df.replace({"NaT": None, "NaN": None, pd.NA: None, np.nan: None})
                df = df.where(pd.notnull(df), None)
                columns = df.columns.tolist()
                values = [tuple(x) for x in df.to_numpy()]

                query = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                )

                # Use your connection pool context
                with self.client.conn_cursor() as (_, cur):
                    execute_values(cur, query, values)

                print(
                    f"[PushDataToPostgres] Inserted {len(values)} rows into {schema_name}.{table_name}"
                )

            except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
                print(f"[PushDataToPostgres] Failed to parse CSV {csv_file}: {exc}")
            except (psycopg2.Error, OSError) as exc:
                print(
                    f"[PushDataToPostgres] Failed to insert data into {schema_name}.{table_name}: {exc}"
                )

    def invoke(self, metadata_file: str, tables_paths: List[str]) -> None:
        """
        Connect to Postgres, read metadata JSON and create schema + tables.
        """
        schema_name = self.create_schema_and_tables(metadata_file)
        self.load_data_into_tables(tables_paths, schema_name)


def load_and_push_fake_data(
    data_folder: str = "data", data_file: str = "metadata_dump.json"
):
    """
    Find the data csv and metadata file in repo
    """
    base = os.path.dirname(__file__)
    metadata_path = os.path.join(base, data_folder, data_file)
    tables_path = os.path.join(base, data_folder, "tables")
    tables: List[str] = []
    for filename in os.listdir(tables_path):
        if filename.endswith(".csv"):
            tables.append(os.path.join(tables_path, filename))

    print(f"Using metadata path: {metadata_path}")
    pusher = PushDataToPostgres()
    pusher.invoke(metadata_path, tables)


if __name__ == "__main__":
    load_and_push_fake_data()
