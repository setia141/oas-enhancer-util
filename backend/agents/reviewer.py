from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from .tools import get_oas_spec, get_postman_collection, get_breaking_changes_policy, submit_review
from .prompts import REVIEWER_INSTRUCTION

reviewer_agent = Agent(
    name="oas_reviewer",
    model=LiteLlm(model="openai/gpt-4.1-mini"),
    description="Reviews an OAS specification and outputs structured improvement suggestions.",
    tools=[get_oas_spec, get_postman_collection, get_breaking_changes_policy, submit_review],
    instruction=REVIEWER_INSTRUCTION,
)
