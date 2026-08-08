"""
LangChain agent for Egeria assistance.

This agent combines LangChain's agent orchestration with our optimized
RAG retrieval tools.
"""

from typing import Optional
from langchain.agents import create_react_agent
from langchain.agents.agent import AgentExecutor
from langchain_ollama import ChatOllama
from langchain.prompts import PromptTemplate

from advisor.tools.rag_tools import get_egeria_tools


# Agent prompt template
EGERIA_AGENT_PROMPT = """You are an expert assistant for the Egeria open metadata and governance platform.
You help users understand and use Egeria's Python library (pyegeria) and related tools.

You have access to the following tools:

{tools}

Tool Names: {tool_names}

When answering questions:
1. Search for relevant code and documentation using the tools
2. Provide clear, accurate answers based on the search results
3. Include code examples when helpful
4. Cite your sources (file paths and collections)

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought: {agent_scratchpad}"""


class EgeriaAgent:
    """
    LangChain-powered agent for Egeria assistance.
    
    Combines:
    - LangChain agent orchestration
    - Our optimized RAG tools (17,997x speedup from caching)
    - Ollama LLM
    """
    
    def __init__(
        self,
        model_name: str = "llama3.1:8b",
        ollama_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        verbose: bool = True
    ):
        """
        Initialize the Egeria agent.
        
        Parameters
        ----------
        model_name : str
            Ollama model name
        ollama_url : str
            Ollama server URL
        temperature : float
            LLM temperature (0.0-1.0)
        verbose : bool
            Whether to show agent reasoning
        """
        # Initialize LLM
        self.llm = ChatOllama(
            model=model_name,
            base_url=ollama_url,
            temperature=temperature
        )
        
        # Get tools
        self.tools = get_egeria_tools()
        
        # Create prompt
        self.prompt = PromptTemplate.from_template(EGERIA_AGENT_PROMPT)
        
        # Create agent
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )
        
        # Create executor
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=verbose,
            max_iterations=5,
            handle_parsing_errors=True
        )
    
    def chat(self, message: str) -> str:
        """
        Chat with the agent.
        
        Parameters
        ----------
        message : str
            User message/question
        
        Returns
        -------
        str
            Agent response
        """
        try:
            result = self.agent_executor.invoke({"input": message})
            return result.get("output", "I couldn't generate a response.")
        except Exception as e:
            return f"Error: {str(e)}"
    
    def reset(self):
        """Reset the agent (clear conversation history if applicable)."""
        # LangChain ReAct agents are stateless by default
        # This method is here for API compatibility
        pass


def create_egeria_agent(
    model_name: str = "llama3.1:8b",
    verbose: bool = True
) -> EgeriaAgent:
    """
    Factory function to create an Egeria agent.
    
    Parameters
    ----------
    model_name : str
        Ollama model name
    verbose : bool
        Whether to show agent reasoning
    
    Returns
    -------
    EgeriaAgent
        Configured agent instance
    """
    return EgeriaAgent(model_name=model_name, verbose=verbose)