import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SlackNotifier:
    def __init__(self):
        self.webhook_url = os.getenv('SLACK_WEBHOOK_URL')
        self.enabled = self.webhook_url is not None

        if not self.enabled:
            logger.warning("Slack integration disabled. SLACK_WEBHOOK_URL not set.")
        else:
            logger.info("Slack integration enabled")

    def send_notification(self, event_type, ticket_data):
        """Send ticket notification to Slack"""
        if not self.enabled:
            return False

        if event_type == 'opened':
            return self._send_ticket_opened(ticket_data)
        elif event_type == 'closed':
            return self._send_ticket_closed(ticket_data)
        return False

    def _send_ticket_opened(self, ticket):
        """Format and send new ticket notification"""
        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 New Support Ticket Created",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket #:*\n{ticket['id']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Urgency:*\n{ticket['urgency']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*User:*\n{ticket['user_name']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*System:*\n{ticket['system']}"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Description:*\n{ticket['description']}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Created at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        return self._post_to_slack(message)

    def _send_ticket_closed(self, ticket):
        """Format and send ticket closed notification with feedback input"""
        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Support Ticket Closed",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket #:*\n{ticket['id']}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Duration:*\n{self._format_duration(ticket)}"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Resolution:*\n{ticket['solution'][:250]}{'...' if len(ticket['solution']) > 250 else ''}"
                    }
                },
                # New block for post-mortem
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Post-Mortem Analysis:*\n{ticket['post_mortem']}"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Closed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
        return self._post_to_slack(message)

    def _format_duration(self, ticket):
        """Calculate and format ticket duration"""
        try:
            created = datetime.fromisoformat(ticket['created_at'])
            closed = datetime.fromisoformat(ticket['closed_at'])
            duration = closed - created

            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)

            if hours >= 1:
                return f"{int(hours)}h {int(minutes)}m"
            return f"{int(minutes)}m {int(seconds)}s"
        except:
            return "N/A"

    def _post_to_slack(self, payload):
        """Send payload to Slack webhook"""
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=5
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")
            return False