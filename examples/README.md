# Examples

Each runs from the repository root with nothing installed beyond the package,
except where noted. `tests/test_examples_run.py` runs every offline one on
every CI build.

| example | what it shows | needs |
|---|---|---|
| [quickstart.py](quickstart.py) | Store, retrieve, inspect the evidence, correct, verify the correction ([QUICKSTART.md](../docs/QUICKSTART.md)) | nothing |
| [reference_agent.py](reference_agent.py) | A complete agent loop: retrieve, decide, cite, get a grant for the exact action, execute through the fence, have the outcome verified, remember what worked. A poisoned web note is refused at the gate | nothing |
| [poisoning_and_rollback.py](poisoning_and_rollback.py) | The governance story: a false memory consolidated into a belief and a procedure, shared, then traced and retracted everywhere | nothing |
| [action_gate.py](action_gate.py) | A tool call gated on its evidence, with a memory retracted between recall and action | nothing |
| [agent_on_the_fabric.py](agent_on_the_fabric.py) | The Claude adapter end to end, with a scripted model; drop the stub to use the live API | nothing (`pip install ".[claude]"` and a key for the live API) |
| [live_memory_os.py](live_memory_os.py) | The whole layer driven by real local models: governed writes, semantic retrieval, federation, retraction | Ollama with `qwen2.5:3b` and `nomic-embed-text` |

Shorter, task-sized snippets are in [docs/COOKBOOK.md](../docs/COOKBOOK.md).
