# Architecture Reconciliation Notes

## Rough Architecture Page Summary
The Rough Architecture (v2.1) document describes Pattern Proof as an automated dark-pattern audit platform with the following core components:
- **API Gateway**: FastAPI for audit management and report retrieval
- **Audit Orchestrator**: Orchestrates task graphs and dispatches work to Kafka
- **Discovery Service**: Extracts website structure (robots.txt, sitemaps, links, JS routes)
- **Static Analysis Pipeline**: DOM, CSS, OCR, and VLM analyzers coordinated by Claude
- **Dynamic Analysis Pipeline**: Browser exploration, state graph building, network inspection, trajectory reasoning
- **Pattern Detection Engine**: Converts evidence into Mathur Taxonomy findings
- **Knowledge Graph Service**: Neo4j-based website and state representation
- **Reporting Service**: Generates JSON, Markdown, and PDF reports
- **Data Layer**: PostgreSQL (system of record), Neo4j (graphs), Redis (cache), Object Storage (artifacts)
- **Messaging**: Kafka for event-driven architecture
- **LLM Architecture**: Claude (managers/orchestration), Gemma 4 31B via Ollama (analysis workers)

## Divergences from System Design Document (authoritative)

### Authentication
- **Rough Architecture says**: "Authentication has been removed from the current scope" with rationale of internal MVP, faster iteration, and no user management requirements yet.
- **System Design Document decided**: Auth IS IN SCOPE with JWT-based authentication, Argon2 hashing, and RBAC.
- **DIVERGENCE SEVERITY**: Major scope difference. The SDD is the authoritative spec; authentication should be implemented.

### Messaging Technology
- **Rough Architecture says**: Kafka for messaging layer.
- **System Design Document decided**: EventBus interface with EagerEventBus (dev) + RedpandaEventBus (prod).
- **DIVERGENCE SEVERITY**: Architectural pattern differs. SDD specifies an abstraction layer (EventBus interface) rather than direct Kafka dependency. This allows for flexibility in dev vs. prod implementations.

### Storage Stack Detail
- **Rough Architecture says**: PostgreSQL, Neo4j, Redis, Object Storage (S3/MinIO), and references Kafka.
- **System Design Document decided**: Supabase (Postgres), MongoDB (Motor), Neo4j, Redis, Supabase Storage.
- **DIVERGENCE SEVERITY**: Database choices differ:
  - Rough uses raw PostgreSQL + S3/MinIO; SDD specifies Supabase (managed Postgres) + Supabase Storage
  - Rough does not mention MongoDB; SDD includes MongoDB with Motor driver
  - Both include Neo4j and Redis

### LLM Provider for Managers
- **Rough Architecture says**: Claude (Anthropic), with responsibilities including Static Analysis Manager, Dynamic Analysis Manager, Audit Orchestrator, Trajectory Reasoning, Report Synthesis.
- **System Design Document decided**: Claude (Anthropic) for managers.
- **DIVERGENCE SEVERITY**: None—both agree on Claude for manager/orchestration roles.

### LLM Provider for Analysis Workers
- **Rough Architecture says**: Gemma 4 31B via Ollama Cloud with PydanticAI access.
- **System Design Document decided**: Gemma 4 31B via Ollama (analyzers).
- **DIVERGENCE SEVERITY**: None—both agree on Gemma 4 31B for analysis workers.

### VLM/Visual Analysis
- **Rough Architecture says**: VLM Analyzer uses Gemini, Gemma, and Llama; states the VLM is NOT the manager (clarification added in v2.1).
- **System Design Document decided**: No explicit VLM mention; focuses on Gemma 4 31B for DOM, CSS, OCR, and Visual analysis.
- **DIVERGENCE SEVERITY**: Minor. Rough provides additional VLM flexibility (Gemini/Gemma/Llama options) but SDD only specifies Gemma 4 31B. The clarification that VLM is not the manager aligns with SDD's manager-worker separation.

## Items consistent across both documents
- **Claude for Orchestration**: Both documents designate Claude (Anthropic) for manager/orchestrator roles.
- **Gemma 4 31B for Analysis**: Both documents specify Gemma 4 31B for worker-level analysis tasks.
- **Pattern Taxonomy**: Both reference Mathur Taxonomy as the primary classification system (SDD also includes DPDP and CCPA/CPRA, but Rough focuses on Mathur).
- **Neo4j for Knowledge Graph**: Both documents include Neo4j for storing website structure and state graphs.
- **Redis for Cache/Metadata**: Both include Redis for caching, locks, and session state.
- **Event-Driven Architecture**: Both documents embrace event-driven, asynchronous execution with worker scaling.
- **Kafka/EventBus Messaging**: Both use a message queue abstraction (Kafka in rough, EventBus interface in SDD).
- **Async Execution & Horizontal Scaling**: Both emphasize fully asynchronous execution and horizontal worker scaling.
- **Multi-Report Formats**: Both support JSON, Markdown, and PDF report generation.

## Open questions or ambiguities noted

1. **Authentication Timeline**: The Rough Architecture removes auth as "out of scope for MVP" but the SDD declares it in scope. Clarification needed: Is the SDD's MVP scope broader, or does the team plan to defer auth implementation despite being documented in SDD?

2. **MongoDB vs. Raw PostgreSQL**: The SDD specifies MongoDB with Motor driver, but the Rough Architecture does not mention MongoDB at all. The Rough document shows only PostgreSQL for the system of record. Clarification needed: Will MongoDB be used for specific collections (e.g., audit metadata, evidence metadata), or is it truly out of the implementation?

3. **Supabase vs. Raw PostgreSQL + S3**: The SDD specifies Supabase (managed Postgres + Supabase Storage), while Rough uses raw PostgreSQL + S3/MinIO. Clarification needed: Is the team using managed Supabase infrastructure or self-hosted Postgres + S3?

4. **EventBus Interface vs. Kafka Direct**: The SDD specifies an EventBus interface abstraction with EagerEventBus (dev) and RedpandaEventBus (prod), while Rough directly mentions Kafka. Clarification needed: Will the codebase implement the EventBus abstraction layer for flexibility, or use Kafka directly?

5. **Pattern Taxonomy Scope**: The SDD mentions Mathur + DPDP + CCPA/CPRA pattern taxonomies, but the Rough Architecture only explicitly documents the Mathur taxonomy. Clarification needed: Will DPDP and CCPA/CPRA detectors be implemented in the same pattern detection pipeline?

6. **Temporal Workflow Orchestration**: The Rough Architecture lists Temporal as "optional for workflow orchestration," but the SDD does not mention it. Clarification needed: Will Temporal be used for complex multi-step workflows, or will task graphs be managed directly by the Audit Orchestrator?
