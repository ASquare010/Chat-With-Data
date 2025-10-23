# common/utils/postgres_client.py
import os
from contextlib import contextmanager
from typing import Optional, Tuple, Any, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import connection
from psycopg2.pool import SimpleConnectionPool
from common.models.db_metadata import DatabaseResult


class PostgresClient:
    """
    Postgres client with a connection pool (psycopg2 SimpleConnectionPool).

    It will prefer environment variables if constructor args are None.
    Defaults are convenient for the docker-compose fake_db:
      POSTGRES_HOST=fake_db
      POSTGRES_PORT=5432
      POSTGRES_DB=chat_with_data_db
      POSTGRES_USER=asquare
      POSTGRES_PASSWORD=bro_secret

    Usage:
        client = PostgresClient()
        client.connect_pool(minconn=1, maxconn=5)
        client.execute("SELECT 1;", fetch=True)
        client.close()
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        # sensible defaults aligned with your docker-compose fake_db service
        self.host = host or os.getenv("POSTGRES_HOST", "localhost")
        self.port = port or int(os.getenv("POSTGRES_PORT", "5432"))
        self.user = user or os.getenv("POSTGRES_USER", "asquare")
        self.password = password or os.getenv("POSTGRES_PASSWORD", "bro_secret")
        self.database = database or os.getenv("POSTGRES_DB", "chat_with_data_db")

        # connection pool (created by connect_pool)
        self._pool: Optional[SimpleConnectionPool] = None

        # single-connection fallback (kept for backward compatibility)
        self.conn: Optional[psycopg2.extensions.connection] = None

    # -------------------------
    # Connection (pool) methods
    # -------------------------
    def connect_pool(self, minconn: int = 1, maxconn: int = 5) -> None:
        """
        Create a SimpleConnectionPool. If a pool already exists, this is a no-op.
        """
        if self._pool:
            return

        dsn = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": self.database,
        }
        try:
            self._pool = SimpleConnectionPool(minconn, maxconn, **dsn)
            print(
                f"[PostgresClient] Created connection pool {minconn}-{maxconn} -> "
                f"{self.user}@{self.host}:{self.port}/{self.database}"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to create connection pool: {exc}") from exc

    def connect(self) -> None:
        """
        Backwards-compatible connect: allocate a pool with small sizes if none exists.
        """
        if self._pool:
            return
        # create a small pool by default
        self.connect_pool(minconn=1, maxconn=5)

    def close(self) -> None:
        """
        Close the connection pool (if present) or the single connection fallback.
        """
        if self._pool:
            try:
                self._pool.closeall()
                print("[PostgresClient] Connection pool closed.")
            finally:
                self._pool = None
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None
                print("[PostgresClient] Single connection closed.")

    @contextmanager
    def conn_cursor(
        self,
    ) -> Iterator[Tuple[psycopg2.extensions.connection, psycopg2.extensions.cursor]]:
        """
        Context manager that yields (conn, cur) and returns the connection to the pool.
        Uses RealDictCursor for fetches.
        """
        # prefer pool
        if self._pool:
            conn: connection = self._pool.getconn()
            try:
                cur: RealDictCursor = conn.cursor(cursor_factory=RealDictCursor)
                yield conn, cur
                # ensure we commit DDL/DML (pool connections may not be autocommit)
                try:
                    conn.commit()
                except Exception:
                    # some operations may require autocommit (DDL). swallow commit errors.
                    pass
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._pool.putconn(conn)
        else:
            # fallback single connection
            if not self.conn or getattr(self.conn, "closed", 1):
                dsn = {
                    "host": self.host,
                    "port": self.port,
                    "user": self.user,
                    "password": self.password,
                    "dbname": self.database,
                }
                self.conn = psycopg2.connect(**dsn)
                self.conn.autocommit = True
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield self.conn, cur
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

    # -------------------------
    # Query execution
    # -------------------------

    def execute(
        self,
        sql_text: Any,
        params: Optional[Tuple] = None,
    ) -> Optional[DatabaseResult]:
        """
        Execute SQL using a pooled connection.
        - sql_text: str or psycopg2.sql.Composed (or other supported SQL object).
        - params: optional tuple for parameterized queries.
        - fetch: whether to call fetchall() and return results.
        - as_dict: if True, rows are returned as list[dict], else list[tuple].

        Returns None if fetch=False. Otherwise returns:
        {'cols': [colname, ...], 'rows': [ {col: val, ...}, ... ] }
        """
        if not self._pool and (not self.conn or getattr(self.conn, "closed", 1)):
            # auto-create pool (backwards compatible)
            self.connect()

        with self.conn_cursor() as (_, cur):
            try:
                # Accept Composed / Identifier / SQL objects and plain strings
                cur.execute(sql_text, params)
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description] if cur.description else []
                return DatabaseResult(sql=sql_text, columns=cols, rows=rows)

            except Exception as exc:
                pretty_sql = (
                    sql_text
                    if isinstance(sql_text, str)
                    else getattr(
                        sql_text, "as_string", lambda *a, **k: "<COMPOSED_SQL>"
                    )()
                )
                print(f"[PostgresClient] SQL execution error: {exc}\nSQL: {pretty_sql}")
                raise

    # -------------------------
    # Helper (smoke test)
    # -------------------------
    def test_connection(self) -> None:
        """Test the pool by executing a simple SELECT 1;"""
        res = self.execute("SELECT 1 as ok;")
        print(f"[PostgresClient] Test query result: {res}")
