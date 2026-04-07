"""
Serviços do módulo de chatbot.

Funções stub preparadas para integração futura com WhatsApp Business API.
"""


def process_chatbot_response(flow_id, step_id, user_response, session_data=None):
    """
    Processa a resposta de um usuário a um passo do chatbot.

    STUB — Esta função será implementada quando a integração real
    com WhatsApp Business API for adicionada. O fluxo esperado:

    1. Buscar o ChatbotStep pelo step_id
    2. Validar a resposta conforme o step_type (email, phone, etc.)
    3. Mapear a resposta para o campo do Lead via lead_field_mapping
    4. Acumular no session_data
    5. Determinar o próximo passo:
       - Se step_type == 'choice', buscar ChatbotChoice selecionada
         e usar next_step (ou avançar por order)
       - Senão, avançar para o próximo step por order
    6. Se não houver próximo passo, executar as ChatbotActions do flow
       (criar lead, notificar, etc.)
    7. Retornar o próximo passo ou mensagem de conclusão

    Args:
        flow_id: PK do ChatbotFlow
        step_id: PK do ChatbotStep atual
        user_response: String com a resposta do usuário
        session_data: Dict acumulado da sessão (nome, email, etc.)

    Returns:
        dict: {
            "next_step_id": int | None,
            "message": str,
            "is_complete": bool,
            "lead_data": dict,
            "status": "stub",
        }
    """
    return {
        "next_step_id": None,
        "message": "Stub: integração não implementada nesta fase.",
        "is_complete": False,
        "lead_data": session_data or {},
        "status": "stub",
        "integration_ready": True,
    }


def create_lead_from_chatbot(empresa, flow, session_data):
    """
    Cria um Lead a partir dos dados coletados pelo chatbot.

    STUB — Será ativada quando o processo completo for implementado.

    O mapeamento de campos é feito via ChatbotStep.lead_field_mapping.
    O lead será criado com:
      - source = 'whatsapp' (ou conforme flow.channel)
      - external_ref = ID da sessão do chatbot
      - Os campos mapeados preenchidos a partir de session_data

    Args:
        empresa: Instância de Empresa (tenant)
        flow: Instância de ChatbotFlow
        session_data: Dict com os dados coletados

    Returns:
        Lead | None
    """
    return None
