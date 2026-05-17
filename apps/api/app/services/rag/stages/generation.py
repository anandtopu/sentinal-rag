"""GenerationStage — LiteLLM completion (or canned abstain answer).

The orchestrator handles the abstain branch externally (skips the budget +
generation stages entirely) so this stage assumes generation is wanted by
the time ``run`` is called.
"""

from __future__ import annotations

from decimal import Decimal

from sentinelrag_shared.llm import LiteLLMGenerator

from app.services.rag.types import QueryContext


class GenerationStage:
    """Stateless — model + base url come from the QueryContext at call time."""

    async def run(self, ctx: QueryContext) -> None:
        if ctx.resolved_prompt is None:
            msg = "GenerationStage requires PromptStage to have resolved a prompt first."
            raise RuntimeError(msg)
        if not ctx.effective_model:
            msg = "GenerationStage requires BudgetStage to have set effective_model first."
            raise RuntimeError(msg)

        generator = LiteLLMGenerator(
            model_name=ctx.effective_model,
            api_base=ctx.ollama_base_url
            if ctx.effective_model.startswith("ollama/")
            else None,
        )
        user_prompt = ctx.resolved_prompt.user_prompt_template.format(
            query=ctx.query.strip(), context=ctx.context_text
        )
        gen_result = await generator.complete(
            system_prompt=ctx.resolved_prompt.system_prompt,
            user_prompt=user_prompt,
            temperature=ctx.generation_cfg.temperature,
            max_tokens=ctx.generation_cfg.max_tokens,
        )
        ctx.answer_text = gen_result.text
        ctx.gen_usage = gen_result.usage
        ctx.gen_cost = gen_result.usage.total_cost_usd or Decimal("0")
        ctx.input_tokens = gen_result.usage.input_tokens
        ctx.output_tokens = gen_result.usage.output_tokens
