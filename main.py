import os
import argparse
from pydantic_ai import Agent
import logfire

logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

def main():
    parser = argparse.ArgumentParser(description="Pydantic AI Hello World")
    parser.add_argument("--use-openai", action="store_true", help="Use OpenAI model instead of TestModel. Requires OPENAI_API_KEY environment variable.")
    args = parser.parse_args()

    print("Running Pydantic AI Hello World...")

    if args.use_openai:
        print("Using OpenAI gpt-4o-mini model.")
        if not os.getenv("OPENAI_API_KEY"):
            print("Error: OPENAI_API_KEY environment variable is not set. Please set it or run without --use-openai to use the test model.")
            return
        agent = Agent('openai:gpt-4o-mini', name='hello_world_agent', system_prompt='Be concise, reply with one sentence.')
    else:
        print("Initializing test model (no API key required).")
        from pydantic_ai.models.test import TestModel
        agent = Agent(TestModel(), name='hello_world_agent', system_prompt='Be concise, reply with one sentence.')

    try:
        result = agent.run_sync('Where does "hello world" come from?')
        output = result.data if hasattr(result, 'data') else getattr(result, 'output', result)
        print("Success! Agent returned:", output)
    except Exception as e:
        print(f"Error running agent: {e}")

if __name__ == '__main__':
    main()
