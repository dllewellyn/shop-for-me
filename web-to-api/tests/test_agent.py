from pydantic_ai.models.test import TestModel

from web_to_api.agent import create_agent


def test_saving_design_requires_explicit_ui_approval() -> None:
    agent = create_agent(TestModel())

    assert agent._function_toolset.tools["save_api_design"].requires_approval is True
    assert agent._function_toolset.tools["investigate_site"].requires_approval is False
