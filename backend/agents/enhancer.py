from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from .tools import get_oas_spec, get_postman_collection, get_breaking_changes_policy, get_review_suggestions, save_enhanced_spec
from .prompts import ENHANCER_INSTRUCTION

enhancer_agent = Agent(
    name="oas_enhancer",
    model=LiteLlm(model="openai/gpt-4o"),
    description="Applies reviewer suggestions to an OAS specification and saves the enhanced spec.",
    tools=[get_oas_spec, get_postman_collection, get_breaking_changes_policy, get_review_suggestions, save_enhanced_spec],
    instruction=ENHANCER_INSTRUCTION,
)
