import pytest
from database import DatabaseManager
from SlackAgent import SlackNotifier
import os
from unittest.mock import patch, MagicMock

def test_real_slack_notification():
    """TESTE REAL: Envia notificação real para o Slack"""
    # Configurar com URL real
    os.environ['SLACK_WEBHOOK_URL'] = 'https://hooks.slack.com/services/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'

    db = DatabaseManager()
    slack = SlackNotifier()
    db.add_ticket_listener(slack.send_notification)

    ticket_id = db.open_ticket(
        "Usuário Real de Teste",
        "Teste de integração com Slack - Por favor ignorar",
        "Sistema de Teste",
        "Medium"
    )

    print(f"✅ Ticket #{ticket_id} criado. Verifique o Slack para confirmar a notificação.")

if __name__ == "__main__":
    test_real_slack_notification()