"""A LangChain retriever over governed memory.

    from memory_fabric.integrations.langchain import fabric_retriever
    retriever = fabric_retriever(agent(fabric, "my-agent"), k=5)
    docs = retriever.invoke("pump 3 seal")          # any LangChain chain or agent
    retriever.verify(docs[0].metadata["memory_id"])  # before acting on it

Built on `AgentClient`, so a chain receives only memories that passed
enforcement, in the agent's own tenant and scope. Each document carries the
memory id, version and any warnings (a contested memory says so), and the
retriever keeps the exposure tokens server-side so `verify` can re-check a
memory immediately before a consequential action -- a retraction issued after
retrieval is caught there.

Needs `langchain_core`, imported only when `fabric_retriever` is called.
"""

from __future__ import annotations

__stability__ = "beta"

from typing import Any

from ..sdk import AgentClient


def fabric_retriever(client: AgentClient, k: int = 5, include_contested: bool = False) -> Any:
    from langchain_core.callbacks import CallbackManagerForRetrieverRun
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever
    from pydantic import ConfigDict, PrivateAttr

    class FabricRetriever(BaseRetriever):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        client: Any
        k: int = 5
        include_contested: bool = False
        _issued: dict[str, Any] = PrivateAttr(default_factory=dict)

        def _get_relevant_documents(
            self, query: str, *, run_manager: CallbackManagerForRetrieverRun
        ) -> list[Document]:
            hits = self.client.recall(query, k=self.k, include_contested=self.include_contested)
            docs = []
            for usable in hits:
                self._issued[usable.memory_id] = usable
                docs.append(Document(page_content=usable.content, metadata={
                    "memory_id": usable.memory_id, "version": usable.version,
                    "type": usable.type, "warnings": list(usable.warnings),
                    "source": "memory-fabric"}))
            return docs

        def verify(self, memory_id: str) -> bool:
            """Whether a memory this retriever returned may still be acted on."""
            usable = self._issued.get(memory_id)
            if usable is None:
                raise KeyError(f"{memory_id} was not returned by this retriever")
            return bool(self.client.verify(usable).usable)

    return FabricRetriever(client=client, k=k, include_contested=include_contested)
