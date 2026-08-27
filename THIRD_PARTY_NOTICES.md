# Third-party notices

This repository contains original workflow, fixture, and controller code. It does not vendor Deep Agents, Deep Agents Code, LangGraph, LangChain, LangSmith, their dependency trees, or any container images.

The optional SDK integration and local examples use separately distributed components:

| Component | Use | License |
|---|---|---|
| [Deep Agents Python](https://github.com/langchain-ai/deepagents) 0.7.8 | External Python candidate-authoring SDK | MIT, LangChain contributors |
| [Deep Agents JavaScript](https://github.com/langchain-ai/deepagentsjs) 1.13.1 | External TypeScript candidate-authoring SDK | MIT, LangChain contributors |
| [LangChain Python Anthropic](https://github.com/langchain-ai/langchain) 1.6.1 | Optional Python Anthropic model integration | MIT, LangChain contributors |
| [LangChain Python Google GenAI](https://github.com/langchain-ai/langchain-google) 4.3.5 | Optional Python Google model integration | MIT, LangChain contributors |
| [LangChain Python Ollama](https://github.com/langchain-ai/langchain) 1.1.0 | Optional Python Ollama model integration | MIT, LangChain contributors |
| [LangChain Python OpenAI](https://github.com/langchain-ai/langchain) 1.6.0 | Optional Python OpenAI model integration | MIT, LangChain contributors |
| [LangChain JavaScript Anthropic](https://github.com/langchain-ai/langchainjs) 1.5.8 | Optional TypeScript Anthropic model integration | MIT, LangChain contributors |
| [LangChain JavaScript Google GenAI](https://github.com/langchain-ai/langchainjs) 2.3.0 | Optional TypeScript Google model integration | MIT, LangChain contributors |
| [LangChain JavaScript Ollama](https://github.com/langchain-ai/langchainjs) 1.3.0 | Optional TypeScript Ollama model integration | MIT, LangChain contributors |
| [LangChain JavaScript OpenAI](https://github.com/langchain-ai/langchainjs) 1.5.10 | Optional TypeScript OpenAI model integration | MIT, LangChain contributors |
| [LangGraph](https://github.com/langchain-ai/langgraph) 1.2.11 | Qualified transitive graph runtime | MIT, LangChain contributors |
| [LangChain](https://github.com/langchain-ai/langchain) 1.3.17 | Qualified transitive agent runtime | MIT, LangChain contributors |
| [LangSmith SDK](https://github.com/langchain-ai/langsmith-sdk) 0.11.1 | Qualified transitive SDK; tracing disabled by default | MIT, LangChain contributors |
| [LangChain JavaScript](https://github.com/langchain-ai/langchainjs) 1.5.10 | TypeScript agent runtime; external npm package | MIT, LangChain contributors |
| [LangGraph JavaScript](https://github.com/langchain-ai/langgraphjs) 1.4.13 | TypeScript graph runtime; external npm package | MIT, LangChain contributors |
| [LangSmith JavaScript SDK](https://github.com/langchain-ai/langsmith-sdk) 0.9.0 | TypeScript transitive SDK; tracing disabled | MIT, LangChain contributors |
| [Node.js](https://nodejs.org/) 22.23.2 Alpine container image | TypeScript SDK smoke runtime | MIT and bundled component licenses |
| [Python](https://www.python.org/) 3.12 container image | Verifier runtime | Python Software Foundation License |
| [PostgreSQL](https://www.postgresql.org/) 14.24 | Disposable relational state | PostgreSQL License |
| [Apache Kafka](https://kafka.apache.org/) 4.3.1 | Disposable event transport | Apache-2.0 |
| [OpenSearch](https://opensearch.org/) 3.8.0 | Disposable search state | Apache-2.0 |
| [Psycopg](https://www.psycopg.org/) 3.2.9 | PostgreSQL client in the verifier image | LGPL-3.0-only |
| [kafka-python](https://github.com/dpkp/kafka-python) 2.3.2 | Kafka client in the verifier image | Apache-2.0 |
| [typing-extensions](https://github.com/python/typing_extensions) 4.16.0 | Psycopg compatibility dependency | PSF-2.0 |

The repository references versioned packages and digest-pinned images; it does
not redistribute them. Qualified transitive package and license evidence is
recorded in `security/dependency-qualification.json` and
`security/typescript-dependency-qualification.json`. Anyone redistributing a
prebuilt verifier or smoke image must preserve applicable notices, satisfy the
Psycopg LGPL requirements, and produce an appropriate software bill of
materials.
