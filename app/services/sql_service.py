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

    async def generate(self, request):
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
             lambda: self.client.chat.completions.create(
                model=self.deployment,
                messages=request["messages"],
                temperature=settings.VANNA_TEMPERATURE,
                top_p=settings.VANNA_TOP_P,
                max_tokens=settings.VANNA_MAX_TOKENS,
             )
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
        return  self._execute_and_extract_results(sql)
    
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
        self.database_url = database_url or settings.DATABASE_URL
        self.query_cache_service = query_cache_service
        self.azure_api_key = azure_api_key or settings.AZURE_OPENAI_API_KEY
        self.azure_endpoint = azure_endpoint or settings.AZURE_OPENAI_ENDPOINT
        self.azure_deployment = azure_deployment or settings.AZURE_OPENAI_DEPLOYMENT

        if not self.azure_api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is required")

        if not self.azure_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required")

        if not self.azure_deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT is required")
        
        pinecone_key = settings.PINECONE_API_KEY if PINECONE_AVAILABLE else None
        self.vanna = VannaAgentWrapper(
            azure_api_key=self.azure_api_key,
            azure_endpoint=self.azure_endpoint,
            azure_deployment = self.azure_deployment,
            database_url=self.database_url,
            pinecone_api_key=pinecone_key
        )
        
        self.pending_queries: Dict[str, Dict[str, Any]] = {}
        self.is_trained = False
        self.schema_context = ""

    def complete_training(self):
        """
        Prepare schema context for Vanna 2.0.
        Note: Vanna 2.0 Agent doesn't use the same training approach as legacy Vanna.
        Instead, we provide schema context with each query.
        """
        logger.info("Preparing schema context for Vanna 2.0...")
        self.schema_context = self._build_schema_context()
        self.is_trained = True
        logger.info("✓ Schema context prepared for Vanna 2.0 Agent!")

    def _build_schema_context(self):
        """
        Build comprehensive schema context by querying database.
        Provides same information as legacy Vanna training.

        Returns:
            Formatted schema documentation string
        """
        schema_parts = []
        schema_parts.append("DATABASE SCHEMA DOCUMENTATION")
        schema_parts.append("="* 60)

        documentation = """
This is an e-commerce database with three main tables:
- customers: Contains customer information including name, email, segment (SMB, Enterprise, Individual), and country
- products: Product catalog with name, category, price, stock quantity, and description
- orders: Customer orders with order date, total amount, status (Pending, Delivered, Cancelled, Processing), and shipping address

The customers table has a one-to-many relationship with orders (one customer can have many orders).

IMPORTANT NOTES:
- For order revenue/pricing, use orders.total_amount (NOT 'price')
- Customer segments: 'SMB', 'Enterprise', 'Individual' (case-sensitive)
- Order statuses: 'Pending', 'Delivered', 'Cancelled', 'Processing' (case-sensitive)
- To join customers and orders: JOIN orders ON customers.id = orders.customer_id
"""

        schema_parts.append(documentation)

        schema_parts.append("\nTABLE SCHEMAS:")
        schema_parts.append("-" * 60)


        schema_parts.append("""
Table: customers
Columns:
  - id (SERIAL PRIMARY KEY)
  - name (VARCHAR) - Customer full name
  - email (VARCHAR) - Customer email address
  - segment (VARCHAR) - One of: 'SMB', 'Enterprise', 'Individual'
  - country (VARCHAR) - Customer country
  - created_at (TIMESTAMP)
  - updated_at (TIMESTAMP)
""")

        schema_parts.append("""
Table: products
Columns:
  - id (SERIAL PRIMARY KEY)
  - name (VARCHAR) - Product name
  - category (VARCHAR) - Product category (Electronics, Software, Hardware, etc.)
  - price (DECIMAL) - Product unit price
  - stock_quantity (INT) - Current inventory count
  - description (TEXT)
  - created_at (TIMESTAMP)
  - updated_at (TIMESTAMP)
""")

        schema_parts.append("""
Table: orders
Columns:
  - id (SERIAL PRIMARY KEY)
  - customer_id (INT) - Foreign key to customers.id
  - order_date (DATE) - Date of order
  - total_amount (DECIMAL) - TOTAL ORDER PRICE (use this for revenue, NOT 'price'!)
  - status (VARCHAR) - One of: 'Pending', 'Delivered', 'Cancelled', 'Processing'
  - shipping_address (TEXT)
  - created_at (TIMESTAMP)
  - updated_at (TIMESTAMP)
""")
        
        schema_parts.append("\nEXAMPLE QUERIES:")
        schema_parts.append("-" * 60)

        examples = [
            ("How many customers do we have?", "SELECT COUNT(*) as customer_count FROM customers;"),
            ("What is the total revenue from all orders?", "SELECT SUM(total_amount) as total_revenue FROM orders;"),
            ("List all delivered orders", "SELECT * FROM orders WHERE status = 'Delivered' ORDER BY order_date DESC;"),
            ("How many orders per customer segment?", "SELECT c.segment, COUNT(o.id) as order_count FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.segment;"),
            ("Top 10 customers by total spending", "SELECT c.name, c.email, SUM(o.total_amount) as total_spent FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name, c.email ORDER BY total_spent DESC LIMIT 10;"),
        ]
        for i, (question, sql) in enumerate(examples, 1):
            schema_parts.append(f"\nExample {i}:")
            schema_parts.append(f"Question: {question}")
            schema_parts.append(f"SQL: {sql}")

        return "\n".join(schema_parts)

    async def generate_sql_for_approval(self, question: str) -> Dict[str, Any]:
        """
        Generate SQL from a natural language question using Vanna 2.0 Agent.
        Returns SQL for user approval before execution.

        NEW: Implements SQL generation caching to save ~$0.08 per cache hit.
        - Cache key: hash(question)
        - Cache TTL: 24 hours (schema relatively stable)
        - Falls back to uncached if Redis unavailable

        Args:
            question: Natural language question

        Returns:
            Dictionary with query_id, question, SQL, status, and cache_hit indicator

        Raises:
            Exception: If schema context not prepared or SQL generation fails
        """
        query_id = str(uuid.uuid4())

        if not self.is_trained:
            raise Exception("Schema context not prepared. Call complete_training() first.")
        
        if self.query_cache_service and self.query_cache_service.enabled:
            cache_key = self.query_cache_service.get_sql_gen_key(question)
            cache_result = self.query_cache_service.get(cache_key, cache_type="sql_gen")

            if cache_result and "sql" in cache_result:
                logger.info(f"SQL generation cache HIT for question: '{question[:50]}...'")

                self.pending_queries[query_id] = {
                    "question": question,
                    'sql': cache_result["sql"],
                    'status': 'pending_approval',
                    'generated_at': pd.Timestamp.now().isoformat(),
                    'cache_hit': True
                }

                return {
                    'query_id': query_id,
                    'question': question,
                    'sql': cache_result["sql"],
                    'explanation': cache_result.get("explanation","This SQL will retrieve data from your database. Please review before approving."),
                    'status': 'pending_approval',
                    'cache_hit': True,
                    'cost_saved': "$0.08"
                }
            
        try:
            sql = await self.vanna.generate_sql_async(
                question=question,
                schema_context=self.schema_context
            )
            explanation = "This SQL will retrieve data from your database. Please review before approving."

            if self.query_cache_service and self.query_cache_service.enabled:
                cache_key = self.query_cache_service.get_sql_gen_key(question)
                cache_value = {
                    "sql": sql,
                    "explanation": explanation,
                    "question": question
                }
                ttl = settings.CACHE_TTL_SQL_GEN
                self.query_cache_service.set(cache_key, cache_value, ttl=ttl, cache_type="sql_gen")
                logger.info(f"SQL generation cache MISS - cached for '{question[:50]}...' (TTL: {ttl}s)")

            self.pending_queries[query_id]={
                "question": question,
                'sql':sql,
                'status':'pending_approval',
                'generated_at': pd.Timestamp.now().isoformat(),
                'cache_hit': False,
                'cost_saved': "$0.00"
            }
            return {
                'query_id': query_id,
                'question': question,
                'sql': sql,
                'explanation': explanation,
                'status': 'pending_approval',
                'cache_hit': False,
                'cost_saved': "$0.00"
            }


        except Exception as e:
            raise Exception(f"Failed to generate SQL: {str(e)}")
        
    async def execute_approved_query(self, query_id: str, approved: bool)-> Dict[str, Any]:
        """
        Execute a SQL query after user approval using Vanna 2.0 Agent.

        NEW: Implements SQL result caching for SELECT queries.
        - Cache key: hash(normalized_sql)
        - Cache TTL: 15 minutes (data changes frequently)
        - Only caches read-only SELECT queries

        Args:
            query_id: ID of the pending query
            approved: Whether the user approved execution

        Returns:
            Dictionary with results or rejection message, plus cache_hit indicator
        """
        if query_id not in self.pending_queries:
            return {
                'error': "query ID not found",
                'status': 'error'
            }
        query_info = self.pending_queries[query_id]
        if not approved:
            del self.pending_queries[query_id]
            return {
                'query_id': query_id,
                'status': 'rejected',
                'message': 'Query execution cancelled by user'
            }
        sql = query_info['sql']
        is_select_query = sql.strip().upper().startswith("SELECT")

        if is_select_query and self.query_cache_service and self.query_cache_service.enabled:
            cache_key = self.query_cache_service.get_sql_result_key(sql)
            cache_result = self.query_cache_service.get(cache_key, cache_type="sql_result")

            if cache_result and "results" in cache_result:
                logger.info(f"SQL result cache HIT for query: '{sql[:50]}...'")

                del self.pending_queries[query_id]
                return {
                    'query_id': query_id,
                    'question': query_info['question'],
                    'sql':sql,
                    'results': cache_result['results'],
                    'result_count': cache_result['result_count'],
                    'status': 'executed',
                    'cache_hit': True,
                    'cache_at': cache_result.get("executed_at")
                }
        try:
            results = await self.vanna.execute_sql_async(sql)
            if is_select_query and self.query_cache_service and self.query_cache_service.enabled:
                cache_key = self.query_cache_service.get_sql_result_key(sql)
                cache_value = {
                    "results": results,
                    "sql": sql,
                    "executed_at": pd.Timestamp.now().isoformat()
                }
                ttl = settings.CACHE_TTL_SQL_RESULT
                self.query_cache_service.set(cache_key, cache_value, ttl=ttl, cache_type="sql_result")
                logger.info(f"SQL result cache MISS - cached for '{sql[:50]}...' (TTL: {ttl}s)")

            del self.pending_queries[query_id]

            return {
                'query_id': query_id,
                'question': query_info['question'],
                'sql': sql,
                'results': results,
                'result_count': len(results),
                'status': 'executed',
                'cache_hit': False
            }
        
        except Exception as e:
            return {
                'query_id': query_id,
                'error': str(e),
                "status": 'error'
            }
        
    def get_pending_queries(self)-> List[Dict[str, Any]]:
        """
        Get list of all pending queries awaiting approval.

        Returns:
            List of pending query information
        """
        return [
            {
                'query_id': qid,
                **info
            }
            for qid, info in self.pending_queries.items()
        ]