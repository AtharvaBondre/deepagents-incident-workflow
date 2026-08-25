# Third-party notices

This repository contains original workflow, fixture, and controller code. It does not vendor Deep Agents, Deep Agents Code, LangGraph, LangChain, LangSmith, their dependency trees, or any container images.

The optional SDK integration and local examples use separately distributed components:

| Component | Use | License |
|---|---|---|
| [Deep Agents](https://github.com/langchain-ai/deepagents) 0.7.8 | External candidate-authoring SDK | MIT, LangChain contributors |
| [LangChain Anthropic](https://github.com/langchain-ai/langchain) 1.6.1 | Optional Anthropic model integration | MIT, LangChain contributors |
| [LangChain Google GenAI](https://github.com/langchain-ai/langchain-google) 4.3.5 | Optional Google model integration | MIT, LangChain contributors |
| [LangChain Ollama](https://github.com/langchain-ai/langchain) 1.1.0 | Optional Ollama model integration | MIT, LangChain contributors |
| [LangChain OpenAI](https://github.com/langchain-ai/langchain) 1.6.0 | Optional OpenAI model integration | MIT, LangChain contributors |
| [LangGraph](https://github.com/langchain-ai/langgraph) 1.2.11 observed on 2026-08-25 | Transitive graph runtime; not yet lock-qualified | MIT, LangChain contributors |
| [LangChain](https://github.com/langchain-ai/langchain) 1.3.17 observed on 2026-08-25 | Transitive agent runtime; not yet lock-qualified | MIT, LangChain contributors |
| [LangSmith SDK](https://github.com/langchain-ai/langsmith-sdk) 0.11.1 observed on 2026-08-25 | Transitive SDK; not yet lock-qualified; tracing disabled by default | MIT, LangChain contributors |
| [Python](https://www.python.org/) 3.12 container image | Verifier runtime | Python Software Foundation License |
| [PostgreSQL](https://www.postgresql.org/) 14.24 | Disposable relational state | PostgreSQL License |
| [Apache Kafka](https://kafka.apache.org/) 4.3.1 | Disposable event transport | Apache-2.0 |
| [OpenSearch](https://opensearch.org/) 3.8.0 | Disposable search state | Apache-2.0 |
| [Psycopg](https://www.psycopg.org/) 3.2.9 | PostgreSQL client in the verifier image | LGPL-3.0-only |
| [kafka-python](https://github.com/dpkp/kafka-python) 2.3.2 | Kafka client in the verifier image | Apache-2.0 |
| [typing-extensions](https://github.com/python/typing_extensions) 4.16.0 | Psycopg compatibility dependency | PSF-2.0 |

The repository references versioned packages and digest-pinned images; it does not redistribute them. Anyone redistributing a prebuilt verifier image must preserve applicable notices, satisfy the Psycopg LGPL requirements, and produce an appropriate software bill of materials.
