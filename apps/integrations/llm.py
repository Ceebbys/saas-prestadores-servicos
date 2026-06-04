"""RV07 (6.1) — Loop agêntico com a API Anthropic (Claude).

Camada fina sobre o SDK oficial: dado system + tools + histórico, roda o loop
manual de *tool use* até o modelo terminar, executando cada ferramenta via um
callback (``tool_executor``) injetado pela camada de negócio (assistant.py).
NENHUMA regra de negócio aqui — só orquestração da conversa com o LLM.

O SDK ``anthropic`` é importado de forma preguiçosa: não pesa no boot e nem
exige a dependência quando o assistente está desligado.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Modelo padrão (o tenant pode trocar nas configurações). Ver claude-api skill.
DEFAULT_MODEL = "claude-opus-4-8"
_MAX_TOKENS = 1024          # respostas de WhatsApp são curtas
_MAX_ITERATIONS = 6         # teto de rodadas de tool use por mensagem


class LLMResult(dict):
    """``{"reply": str, "actions": list[dict], "error": str | None}``."""


def run_agentic_loop(
    *,
    api_key: str,
    model: str,
    system: str,
    tools: list[dict],
    messages: list[dict],
    tool_executor: Callable[[str, dict], dict],
    max_tokens: int = _MAX_TOKENS,
    max_iterations: int = _MAX_ITERATIONS,
) -> LLMResult:
    """Roda a conversa com o Claude até ``end_turn``, executando tools no caminho.

    ``tool_executor(name, input) -> {"ok": bool, "message": str}`` é a ponte com
    o Django (criar lead/proposta). Tudo defensivo: qualquer falha vira um
    ``error`` no resultado, nunca levanta.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic SDK não instalado; assistente IA indisponível")
        return LLMResult(reply="", actions=[], error="sdk_missing")

    if not api_key:
        return LLMResult(reply="", actions=[], error="no_api_key")

    client = anthropic.Anthropic(api_key=api_key)
    # system + tools são estáveis → cacheáveis como prefixo. As mensagens variam.
    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
    ]
    convo: list[dict] = list(messages)
    actions: list[dict] = []

    for _ in range(max_iterations):
        try:
            resp = client.messages.create(
                model=model or DEFAULT_MODEL,
                max_tokens=max_tokens,
                system=system_blocks,
                tools=tools,
                messages=convo,
            )
        except anthropic.AuthenticationError:
            return LLMResult(reply="", actions=actions, error="auth")
        except anthropic.RateLimitError:
            return LLMResult(reply="", actions=actions, error="rate_limit")
        except anthropic.APIError as exc:  # 4xx/5xx da API
            logger.warning("anthropic APIError: %s", exc)
            return LLMResult(reply="", actions=actions, error="api_error")
        except Exception:  # noqa: BLE001 — rede, etc.
            logger.exception("anthropic call failed")
            return LLMResult(reply="", actions=actions, error="unexpected")

        if resp.stop_reason == "tool_use":
            # Preserva o turno do assistente (inclui os blocos tool_use)
            convo.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_input = dict(block.input or {})
                try:
                    result = tool_executor(block.name, tool_input)
                except Exception:  # noqa: BLE001
                    logger.exception("tool %s falhou", block.name)
                    result = {"ok": False, "message": "erro ao executar a ação"}
                actions.append({"tool": block.name, "input": tool_input, "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result.get("message")
                    or ("ok" if result.get("ok") else "falhou"),
                    "is_error": not result.get("ok", False),
                })
            convo.append({"role": "user", "content": tool_results})
            continue

        # end_turn (ou parada normal) → texto final
        reply = " ".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
        return LLMResult(reply=reply, actions=actions, error=None)

    return LLMResult(reply="", actions=actions, error="max_iterations")
