# CrewAI

Give each crew member its own agent identity, so every memory records who
wrote it and the dashboard can tell their stories apart.

```bash
pip install crewai
```

```python
from crewai import Agent, Crew, Task
from crewai.tools import tool

from memory_fabric import MemoryFabric
from memory_fabric.integrations.tools import FabricTools
from memory_fabric.sdk import agent

fabric = MemoryFabric("memory/store.db")
researcher_mem = FabricTools(agent(fabric, "researcher"))
writer_mem = FabricTools(agent(fabric, "writer"))


@tool("Remember a finding")
def remember_finding(content: str) -> dict:
    """Record one durable, sourced finding."""
    return researcher_mem.call("remember", {"content": content})


@tool("Recall findings")
def recall_findings(query: str) -> dict:
    """Recall reviewed findings, each with a trust summary."""
    return writer_mem.call("recall", {"query": query})


researcher = Agent(role="Researcher", goal="Find and record facts",
                   backstory="Careful, cites sources.", tools=[remember_finding])
writer = Agent(role="Writer", goal="Write from recorded facts only",
               backstory="Never states what was not recalled.", tools=[recall_findings])
crew = Crew(agents=[researcher, writer],
            tasks=[Task(description="Research pump P-14 settings", agent=researcher,
                        expected_output="facts recorded"),
                   Task(description="Write the maintenance note", agent=writer,
                        expected_output="a note citing memory ids")])
crew.kickoff()
```

The researcher's findings are candidates until reviewed
(`memory-fabric review`, then `validate` and share to the team), so the
writer only builds on what a person accepted. For tools that change
something, wrap them with `FabricTools.guarded` as in the
[LangGraph guide](langgraph.md).
