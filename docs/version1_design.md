# GenAR PADER - Version 1 Design Document

## Vision
While Version 0 successfully established a grounded, deterministic-first prototype for PADER generation using a static offline dataset, Version 1 aims to evolve this foundation into a robust, reusable, and configurable pharmacovigilance reporting platform. The goal is to support multiple regulatory report types (PSUR, PBRER, DSUR), integrate with live regulatory data systems, and provide a comprehensive reviewer interface.

## 1. Reusable Report Configurations
- **Dynamic Templates:** Transition from hardcoded PADER sections to a YAML/JSON configuration layer defining report templates.
- **Section Dependencies:** Implement DAG-based (Directed Acyclic Graph) dependency resolution for sections so that evidence flows dynamically.
- **Report Types:** Enable support for other periodic formats such as Periodic Safety Update Reports (PSUR) and Development Safety Update Reports (DSUR) simply by swapping the configuration template.

## 2. Expanded Deterministic Analytics & Integrations
- **Company Core Data Sheet (CCDS) Integration:** Implement a Retrieval-Augmented Generation (RAG) vector database or a structured taxonomy parser to automatically evaluate the **Expectedness** of reactions against authorized product labels.
- **Regulatory Database API:** Connect directly to regulatory systems to pull the **History of Actions**, eliminating the current data limitation.
- **MedDRA SOC Ontology:** Integrate a MedDRA dictionary API to automatically map Preferred Terms (PTs) to their higher-level System Organ Classes (SOCs), allowing for standardized hierarchical analysis.

## 3. Advanced Context & Evaluation
- **Configurable Prompts:** Decouple prompts from the Python codebase, loading them from versioned external templates.
- **Evidence Tracing UI:** Build a frontend reviewer interface where clicking a generated LLM sentence highlights the exact deterministic `EvidenceItem` and raw source rows that produced it.
- **Previous-Report Comparison:** Inject the previous reporting period's context to enable the LLM to automatically summarize longitudinal changes (e.g., "Reaction X increased by 15% compared to the 2025 PADER").
- **Stronger Evaluation:** Expand the `PADEREvaluator` to use a secondary LLM for fluency, tone, and formatting scoring, alongside the primary deterministic grounding checks.

## 4. Operational & Review Enhancements
- **Targeted Section Regeneration:** A rich UI allowing medical writers to explicitly reject a single section, provide fine-tuning notes, and regenerate it without rebuilding the entire document.
- **Dataset & Model Versioning:** Every generated report will cryptographically bind its output to the specific hash of the raw dataset, the LLM prompt version, and the model weights used, ensuring perfect auditability.
- **Configurable LLM Providers:** Provide a plug-and-play adapter interface for local open-source models (e.g., Llama 3) for highly sensitive on-premise execution, alongside commercial APIs.
