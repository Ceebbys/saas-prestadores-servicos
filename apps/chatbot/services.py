"""
Serviços do módulo de chatbot.

A criação de leads é delegada para apps.automation.services, que
implementa o pipeline completo com rastreabilidade.
O process_chatbot_response permanece como stub até integração com
WhatsApp Business API.
"""


def process_chatbot_response(flow_id, step_id, user_response, session_data=None):
    """
    Processa a resposta de um usuário a um passo do chatbot.

    STUB — Será implementada com a integração WhatsApp Business API.
    Quando is_complete=True, deve chamar create_lead_from_chatbot().

    Args:
        flow_id: PK do ChatbotFlow
        step_id: PK do ChatbotStep atual
        user_response: String com a resposta do usuário
        session_data: Dict acumulado da sessão (nome, email, etc.)

    Returns:
        dict com next_step_id, message, is_complete, lead_data, status
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

    Delega para apps.automation.services.create_lead_from_chatbot,
    que implementa criação real com rastreabilidade via AutomationLog.

    Args:
        empresa: Instância de Empresa (tenant)
        flow: Instância de ChatbotFlow
        session_data: Dict com os dados coletados

    Returns:
        Lead instance
    """
    from apps.automation.services import create_lead_from_chatbot as _create_lead
    return _create_lead(empresa, flow, session_data)
