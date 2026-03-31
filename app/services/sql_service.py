"""
SQL Service - Vanna 2.0 Agent Framework Implementation
Handles Text-to-SQL conversion using Vanna.ai 2.0 with OpenAI and PostgreSQL.
"""

from typing import Dict, Any, List, Optional
import uuid
import asyncio
import pandas as pd
import logging
from openai import AzureOpenAI
from app.config import settings

logger = logging.getLogger("rag_app.sql_service")

from vanna import Agent
from vanna.integrations.openai import OpenAILlmService
from vanna.integrations.postgres import PostgresRunner
from vanna.core.registry import ToolRegistry
from vanna.tools import RunSqlTool
from vanna.core.user import UserResolver, User, RequestContext

class AzureLlmService:
    def __init__(self, api_key, endpoint, deployment):
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-02-15-preview"
        )
        self.deployment = deployment
    def _build_payload(self, request):
        return {
            "messages": request["messages"]
        }
    async def generate(self, request):
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=request["messages"],
            temperature=settings.VANNA_TEMPERATURE,
            top_p=settings.VANNA_TOP_P
        )
        return response.choices[0].message.content
    
try:
    from vanna.integrations.pinecone import PineconeAgentMemory
    PINECONE_AVAILABLE = True
except ImportError:
    PINECONE_AVAILABLE = False
    from vanna.integrations.local.agent_memory import DemoAgentMemory

class SimpleUserResolver(UserResolver):
    """Simple user resolver for SQL service - grants full access."""
    async def resolve_user(self, request_context: RequestContext)-> User:
        return User(
            id="sql_service_user",
            email="sql@service.local",
            group_memberships=['user','admin']
        )
    
class VannaAgentWrapper:
    """
    Wrapper around Vanna 2.0 Agent for synchronous use in FastAPI.
    Handles async-to-sync conversion and component extraction.
    """
    def __init(
        self,
        azure_api_key: str,
        azure_endpoint: str,
        azure_deployment: str,
        database_url: str,
        pinecone_api_key: Optional[str] = None
    ):
        """
        Initialize Vanna 2.0 Agent with all components.

        Args:
            openai_api_key: OpenAI API key for GPT-4o
            database_url: PostgreSQL connection string
            pinecone_api_key: Optional Pinecone API key for persistent memory
        """
        self.llm = AzureLlmService(
            api_key=azure_api_key,
            endpoint=azure_endpoint,
            deployment=azure_deployment
        )
        logger.info(
            f"Configuring SQL LLM with deterministic settings: "
            f"temperature={settings.VANNA_TEMPERATURE}, "
            f"top_p={settings.VANNA_TOP_P}, "
            f"seed={settings.VANNA_SEED}"
        )

        original_build_payload = self.llm._build_payload

        def deterministic_build_payload(request):
            """Wraps Vanna's _build_payload to add temperature, top_p, and seed."""
            payload = original_build_payload(request)

            payload['temperature'] = settings.VANNA_TEMPERATURE
            payload['top_p'] = settings.VANNA_TOP_P
            payload['seed'] = settings.VANNA_SEED

            if settings.VANNA_MAX_TOKENS:
                payload['max_tokens'] = settings.VANNA_MAX_TOKENS

            logger.debug(f"SQL LLM payload: {payload}")
            return payload
        
        self.llm._build_payload = deterministic_build_payload

        self.postgres_runner = PostgresRunner(
            connection_string=database_url
        )
        self.tool = ToolRegistry()
        self.tool.register_local_tool(
            RunSqlTool(sql_runner=self.postgres_runner),
            access_groups=['user', 'admin']
        )

        self.user_resolver = SimpleUserResolver()

        if PINECONE_AVAILABLE and pinecone_api_key:
            logger.info(f"Using Pinecone for SQL Agent memory (index: {settings.VANNA_PINECONE_INDEX})")
            self.memory = PineconeAgentMemory(
                api_key=pinecone_api_key,
                index_name=settings.VANNA_PINECONE_INDEX,
                environment="us-east-1",
                dimension=1536,
                metric="cosine"
            )
        else:
            logger.warning("Using in-memory storage for SQL Agent (data will not persist)")
            self.memory = DemoAgentMemory()

        self.agent = Agent(
            llm_service=self.llm,
            tool_registry=self.tool,
            user_resolver=self.user_resolver,
            agent_memory=self.memory
        )
        logger.info("✓ Vanna 2.0 Agent initialized successfully")

    async def generate_sql_async(self, question: str, schema_context: str = ""):
        """
        Generate SQL from natural language question (async).

        Args:
            question: Natural language question
            schema_context: Database schema documentation

        Returns:
            Generated SQL query string

        Raises:
            ValueError: If Agent fails to generate SQL
        """
        if schema_context:
            full_message = f"{schema_context}\n\nQUESTION: {question}"
        else:
            full_message =  question
        
        return await self._extract_sql_from_agent(full_message)
    
    async def _extract_sql_from_agent(self, message: str)-> str:
        """
        Extract SQL from Agent's UI components.

        Args:
            message: Full message including schema context and question

        Returns:
            Extracted SQL query

        Raises:
            ValueError: If no SQL found in Agent response
        """
        request_context = RequestContext()
        sql = None

        async for component in self.agent.send_message(
            request_context=request_context,
            message=message
        ):
            rich_comp = component.rich_component

            if hasattr(rich_comp, 'metadata') and rich_comp.metadata:
                if 'sql' in rich_comp.metadata:
                    sql = rich_comp.metadata['sql']
            
            if hasattr(rich_comp, 'content') and rich_comp.content:
                content = str(rich_comp.content)

                if '```sql' in content.lower():
                    parts = content.split('```')
                    for part in parts:
                        if part.strip().lower().startswith('sql'):
                            sql = part[3:].strip()
        
        if not sql:
            raise ValueError("Agent did not generate SQL. Please try rephrasing your question.")
        return sql
    
    async def execute_sql_async(self, sql: str)-> List[Dict[str, Any]]:
        """
        Execute SQL and return results (async).

        Args:
            sql: SQL query to execute

        Returns:
            List of row dictionaries

        Raises:
            Exception: If SQL execution fails
        """
        return await self._execute_and_extract_results(sql)
    
    def _execute_and_extract_results(self, sql: str)-> List[Dict[str, Any]]:
        """
        Execute SQL directly using psycopg2 and return results.

        PostgresRunner.run_sql() is designed to be called by the Agent as a Tool,
        not directly. For manual SQL execution, we use psycopg2 directly.

        Args:
            sql: SQL query to execute

        Returns:
            List of row dictionaries
        """
        try:
            import psycopg2
            import psycopg2.extras
            import socket
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

            conn_str = self.postgres_runner.connection_string
            parsed = urlparse(conn_str)

            hostname = parsed.hostname
            try:
                logger.debug(f"Resolving hostname {hostname} to IPv4...")
                addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
                ipv4_address = addr_info[0][4][0]
                logger.info(f"Resolved {hostname} to IPv4: {ipv4_address}")

                conn_str = conn_str.replace(hostname, ipv4_address)
            except socket.gaierror as e:
                logger.warning(f"Failed to resolve hostname to IPv4: {e}, using original hostname")

            conn = psycopg2.connect(conn_str)

            try:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute(sql)

                rows = cursor.fetchall()

                results = [dict(row) for row in rows]
                cursor.close()
                conn.close()

                return results
            except Exception as e:
                conn.close()
                raise e
        except Exception as e:
            logger.error(f"SQL execution failed: {e}")
            raise ValueError(f"Failed to execute SQL: {str(e)}")

class TextToSQLService:
    """
    Service for converting natural language to SQL using Vanna.ai 2.0 Agent Framework.
    Maintains compatibility with existing FastAPI endpoints.
    """
    def __init__(
            self,
            database_url: str | None = None,
            azure_api_key: str | None = None,
            azure_endpoint: str | None = None,
            azure_deployment: str | None = None,
            query_cache_service=None
    ):
        """
        Initialize the Text-to-SQL service with Vanna 2.0 Agent.

        Args:
            database_url: PostgreSQL connection string
            openai_api_key: OpenAI API key
            query_cache_service: Optional QueryCacheService for SQL caching

        Raises:
            ValueError: If required credentials are missing
        """
        self.azure_api_key = azure_api_key or settings.AZURE_OPENAI_API_KEY
        self.azure_endpoint = azure_endpoint or settings.AZURE_OPENAI_ENDPOINT
        self.azure_deployment = azure_deployment or settings.AZURE_OPENAI_DEPLOYMENT

        if not self.azure_api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is required")

        if not self.azure_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required")

        if not self.azure_deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT is required")