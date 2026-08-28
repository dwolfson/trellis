"""AgentStack A2A server — each specialized agent as its own discoverable endpoint.

Each agent runs on its own port so external orchestrators and the BeeAI platform
can call them independently. The orchestrator on the base port routes by intent.

Default ports (base_port = 8080):
  8080  orchestrator  — routes to the right specialist, general RAG fallback
  8081  stats         — GitHub statistics and commit trends
  8082  code          — source code search
  8083  docs          — documentation and conceptual Q&A
  8084  health        — community health and maintenance assessment
  8085  compare       — side-by-side multi-project comparison

Agents that require a project scope (stats, health) use the A2A input_required
pattern: if they cannot infer the project from the query, they ask the user and
resume when the user replies.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

from a2a.types import AgentSkill, Message, Part, TaskState, TaskStatus, TextPart
from agentstack_sdk.server import Server
from agentstack_sdk.server.context import RunContext


# Port offsets from base_port for each agent
_AGENT_OFFSETS: dict[str, int] = {
    "orchestrator": 0,
    "stats": 1,
    "code": 2,
    "docs": 3,
    "health": 4,
    "compare": 5,
    "integration": 6,
}


def _text(message: Message) -> str:
    """Extract plain text from an A2A Message."""
    parts = []
    for part in message.parts or []:
        root = part.root
        if hasattr(root, "text"):
            parts.append(root.text)
    return " ".join(parts).strip()


def _project_scope(query: str) -> tuple[str, str | None]:
    """Split 'project:<slug> <question>' into (question, slug). Returns (query, None) if no prefix."""
    if query.lower().startswith("project:"):
        head, _, rest = query.partition(" ")
        return rest.strip(), head.split(":", 1)[1].strip()
    return query, None


def _ask_project_status(context: RunContext) -> TaskStatus:
    """Build an input_required TaskStatus listing available projects."""
    try:
        from resource_explorer.registry import ProjectRegistry
        slugs = [p.slug for p in ProjectRegistry().list_all()]
        available = ", ".join(slugs) if slugs else "none registered"
    except Exception:
        available = "unknown"
    text = (
        f"Which project are you asking about? "
        f"Available projects: {available}. "
        f"Reply with the project name or 'project:<slug> <question>'."
    )
    return TaskStatus(
        state=TaskState.input_required,
        message=Message(
            role="agent",
            parts=[Part(root=TextPart(text=text))],
            messageId=str(uuid4()),
            taskId=context.task_id,
            contextId=context.context_id,
        ),
    )


def _slug_from_reply(reply: Message | None) -> str | None:
    """Extract a project slug from the user's clarification reply."""
    if not reply:
        return None
    from resource_explorer.agents.base import BaseExplorerAgent
    text = _text(reply)
    query, explicit = _project_scope(text)
    if explicit:
        return explicit
    # Use inference on the reply text
    class _Probe(BaseExplorerAgent):
        def system_prompt(self): return ""
        def tools(self): return []
        def handle(self, *a, **kw): return ""
    return _Probe()._infer_project_slug(text)


# ── per-agent Server factories ─────────────────────────────────────────────────

def _stats_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Statistics",
        description=(
            "Answers quantitative questions about GitHub projects: stars, forks, "
            "contributors, commits, releases, lines of code, language breakdown, "
            "and committer trends. Prefix with 'project:<slug>' to scope."
        ),
        skills=[
            AgentSkill(id="project_stats", name="Project Statistics",
                       description="Stars, forks, contributors, commit counts, releases, LOC, languages"),
            AgentSkill(id="top_committers", name="Top Committers",
                       description="Ranked list of contributors by commit count over the last 90 days"),
            AgentSkill(id="commit_activity", name="Commit Activity Trends",
                       description="Weekly commit cadence chart over the last 90 days"),
        ],
    )
    async def stats_fn(message: Message, context: RunContext) -> AsyncGenerator:
        from resource_explorer.agents.stats_agent import StatsAgent
        query, slug = _project_scope(_text(message))
        agent = StatsAgent()
        if not slug:
            slug = agent._infer_project_slug(query)
        if not slug:
            reply: Message = yield _ask_project_status(context)
            slug = _slug_from_reply(reply)
        yield agent.handle(query, resource_slug=slug)

    return server


def _code_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Code Search",
        description=(
            "Searches indexed source code to find implementations, classes, functions, "
            "and usage examples across Python, JavaScript, Java, and Go. "
            "Prefix with 'project:<slug>' to scope."
        ),
        skills=[
            AgentSkill(id="code_search", name="Code Search",
                       description="Find implementations, methods, and classes in source code"),
            AgentSkill(id="usage_examples", name="Usage Examples",
                       description="Find how a class or function is used across the codebase"),
        ],
    )
    def code_fn(message: Message) -> str:
        from resource_explorer.agents.code_agent import CodeAgent
        query, slug = _project_scope(_text(message))
        return CodeAgent().handle(query, resource_slug=slug)

    return server


def _docs_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Documentation",
        description=(
            "Answers conceptual questions from indexed project documentation: "
            "READMEs, architecture guides, API references, PDFs, and web docs. "
            "Prefix with 'project:<slug>' to scope."
        ),
        skills=[
            AgentSkill(id="conceptual_qa", name="Conceptual Q&A",
                       description="Architecture, design patterns, getting started, configuration"),
            AgentSkill(id="api_reference", name="API Reference",
                       description="Endpoint definitions, parameter descriptions, examples"),
        ],
    )
    def docs_fn(message: Message) -> str:
        from resource_explorer.agents.doc_agent import DocAgent
        query, slug = _project_scope(_text(message))
        return DocAgent().handle(query, resource_slug=slug)

    return server


def _health_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Health",
        description=(
            "Assesses community health and maintenance status of GitHub projects: "
            "activity trends, bus factor, PR throughput, and release cadence. "
            "Prefix with 'project:<slug>' to scope."
        ),
        skills=[
            AgentSkill(id="health_score", name="Health Assessment",
                       description="Activity status, bus factor, and maintenance indicators"),
            AgentSkill(id="pr_metrics", name="PR Metrics",
                       description="Open/closed PR counts and merge rate from live GitHub API"),
        ],
    )
    async def health_fn(message: Message, context: RunContext) -> AsyncGenerator:
        from resource_explorer.agents.health_agent import HealthAgent
        query, slug = _project_scope(_text(message))
        agent = HealthAgent()
        if not slug:
            slug = agent._infer_project_slug(query)
        if not slug:
            reply: Message = yield _ask_project_status(context)
            slug = _slug_from_reply(reply)
        yield agent.handle(query, resource_slug=slug)

    return server


def _compare_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Compare",
        description=(
            "Produces structured side-by-side comparisons of two or more GitHub projects "
            "across code architecture, documentation, statistics, and community health. "
            "Name the projects in the question, e.g. 'compare arrow and spark'."
        ),
        skills=[
            AgentSkill(id="project_comparison", name="Project Comparison",
                       description="Side-by-side analysis of two or more indexed projects"),
        ],
    )
    async def compare_fn(message: Message, context: RunContext) -> AsyncGenerator:
        from resource_explorer.agents.compare_agent import CompareAgent
        query = _text(message)
        agent = CompareAgent()
        slugs = agent._infer_all_project_slugs(query)

        if len(slugs) < 2:
            try:
                from resource_explorer.registry import ProjectRegistry
                available = ", ".join(p.slug for p in ProjectRegistry().list_all())
            except Exception:
                available = "unknown"
            reply: Message = yield TaskStatus(
                state=TaskState.input_required,
                message=Message(
                    role="agent",
                    parts=[Part(root=TextPart(text=(
                        f"Which two projects would you like to compare? "
                        f"Available: {available}. "
                        "Reply with both project names, e.g. 'compare egeria and agentstack'."
                    )))],
                    messageId=str(uuid4()),
                    taskId=context.task_id,
                    contextId=context.context_id,
                ),
            )
            if reply:
                for s in agent._infer_all_project_slugs(_text(reply)):
                    if s not in slugs:
                        slugs.append(s)

        # Build a query that includes resolved slugs so CompareAgent can find them
        combined = (" ".join(slugs) + " " + query) if slugs else query
        yield agent.handle(combined)

    return server


def _integration_server() -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer: Integration",
        description=(
            "Answers 'how do X and Y work together?' questions across two or more LF AI projects. "
            "Checks for shared contributors, explicit integration docs, compatible interfaces, "
            "and complementary feature sets. Name both projects in the question."
        ),
        skills=[
            AgentSkill(id="integration_analysis", name="Integration Analysis",
                       description="Ecosystem fit, shared contributors, and cross-project integration guidance"),
        ],
    )
    async def integration_fn(message: Message, context: RunContext) -> AsyncGenerator:
        from resource_explorer.agents.integration_agent import IntegrationAgent
        query = _text(message)
        agent = IntegrationAgent()
        slugs = agent._infer_all_project_slugs(query)

        if len(slugs) < 2:
            try:
                from resource_explorer.registry import ProjectRegistry
                available = ", ".join(p.slug for p in ProjectRegistry().list_all())
            except Exception:
                available = "unknown"
            reply: Message = yield TaskStatus(
                state=TaskState.input_required,
                message=Message(
                    role="agent",
                    parts=[Part(root=TextPart(text=(
                        f"Which two projects should I check for integration? "
                        f"Available: {available}. "
                        "Reply with both project names, e.g. 'egeria and agentstack'."
                    )))],
                    messageId=str(uuid4()),
                    taskId=context.task_id,
                    contextId=context.context_id,
                ),
            )
            if reply:
                for s in agent._infer_all_project_slugs(_text(reply)):
                    if s not in slugs:
                        slugs.append(s)

        combined = (" ".join(slugs) + " " + query) if slugs else query
        yield agent.handle(combined)

    return server


def _orchestrator_server(agent_ports: dict[str, int]) -> Server:
    server = Server()

    @server.agent(
        name="Resource Explorer",
        description=(
            "Multi-agent RAG assistant for exploring GitHub projects. "
            "Classifies query intent and routes to the appropriate specialist. "
            "Prefix with 'project:<slug>' to scope to one project."
        ),
        skills=[
            AgentSkill(id="stats", name="Statistics",
                       description=f"Delegates to stats agent — port {agent_ports.get('stats', 8081)}"),
            AgentSkill(id="code_search", name="Code Search",
                       description=f"Delegates to code agent — port {agent_ports.get('code', 8082)}"),
            AgentSkill(id="documentation", name="Documentation",
                       description=f"Delegates to docs agent — port {agent_ports.get('docs', 8083)}"),
            AgentSkill(id="health", name="Health",
                       description=f"Delegates to health agent — port {agent_ports.get('health', 8084)}"),
            AgentSkill(id="compare", name="Compare",
                       description=f"Delegates to compare agent — port {agent_ports.get('compare', 8085)}"),
            AgentSkill(id="integration", name="Integration",
                       description=f"Delegates to integration agent — port {agent_ports.get('integration', 8086)}"),
            AgentSkill(id="general", name="General RAG",
                       description="General-purpose RAG across all indexed content"),
        ],
        version="1.0.0",
    )
    def orchestrator_fn(message: Message) -> str:
        from resource_explorer.rag_system import RAGSystem
        query, slug = _project_scope(_text(message))
        return RAGSystem().query(query, resource_slug=slug)

    return server


# ── entry points ───────────────────────────────────────────────────────────────

async def _serve_all(host: str, base_port: int) -> None:
    agent_ports = {name: base_port + offset for name, offset in _AGENT_OFFSETS.items()}
    servers = [
        _orchestrator_server(agent_ports),
        _stats_server(),
        _code_server(),
        _docs_server(),
        _health_server(),
        _compare_server(),
        _integration_server(),
    ]
    print(f"Starting {len(servers)} agents:")
    for name, offset in _AGENT_OFFSETS.items():
        print(f"  {name:14} → http://{host}:{base_port + offset}")
    await asyncio.gather(*(
        s.serve(host=host, port=base_port + offset)
        for s, offset in zip(servers, _AGENT_OFFSETS.values())
    ))


def run(host: str = "0.0.0.0", port: int = 8100, all_agents: bool = False) -> None:
    if all_agents:
        asyncio.run(_serve_all(host, port))
    else:
        agent_ports = {name: port + offset for name, offset in _AGENT_OFFSETS.items()}
        _orchestrator_server(agent_ports).run(host=host, port=port)
