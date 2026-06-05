# Pattern Proof System Prompts
These files are the source prompts for LLM-powered managers, analyzers, and synthesis agents.

Runtime code should load these files from `prompts/` and pass the relevant task payload as user/developer context. Do not inline long prompt strings in service modules.

## Model routing
- Claude via Anthropic/PydanticAI: orchestration, task planning, trajectory reasoning, report synthesis.
- Gemma 4 31B via Ollama Cloud/PydanticAI: webpage analysis over DOM, CSS, OCR, accessibility, screenshots, and extracted UI evidence.

## Prompt inventory
- `static_analysis_manager.md`
- `dom_analyzer.md`
- `css_analyzer.md`
- `ocr_analyzer.md`
- `accessibility_analyzer.md`
- `visual_analyzer.md`
- `dynamic_analysis_manager.md`
- `browser_exploration_agent.md`
- `trajectory_reasoner.md`
- `report_synthesizer.md`
- `privacy_taxonomy_classifier.md`
