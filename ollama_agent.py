import logging
import re
import time
import requests
import ollama
from database import DatabaseManager
from SlackAgent import SlackNotifier

logger = logging.getLogger(__name__)

class IncidentAgent:
    def __init__(self):
        self.db = DatabaseManager()
        self.slack = SlackNotifier()
        self.ticket_mode = False
        self.resolution_mode = False
        self.ticket_data = {}
        self.active_ticket_id = None
        self.suggestions = []  # Lista para armazenar todas as sugestões
        self.suggestion_count = 0
        self.required_steps = ['user_name', 'system', 'urgency']
        self.step_names = {
            'user_name': 'full name',
            'system': 'affected system/application',
            'urgency': 'urgency level (Low, Medium, High, Critical)'
        }
        self.current_step = 0
        self.ollama_available = self._check_ollama_connection()

        if not self.ollama_available:
            logger.warning("Ollama is unavailable. Using fallback mode.")

        self.db.add_ticket_listener(self.slack.send_notification)
        self.db.add_ticket_listener(self._log_ticket_event)

        self.SCOPE_PROMPT = (
            "Classify if this request is about IT incidents (systems, networks, hardware, software). "
            "Respond only with 'YES' or 'NO'. Rules:\n"
            "- Technical problems = YES\n"
            "- Other subjects (HR, finance, general) = NO\n"
            "Examples:\n"
            "'Email not working' = YES\n"
            "'Salary increase' = NO\n"
            "Request: {input}"
        )

    def _log_ticket_event(self, event_type, ticket_data):
        logger.info(f"Ticket event: {event_type} - Ticket #{ticket_data.get('id', 'N/A')}")

    def _check_ollama_connection(self):
        try:
            response = requests.get('http://localhost:11434', timeout=5)
            return response.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

    def _is_it_related(self, user_input):
        if not self.ollama_available:
            return True

        try:
            prompt = self.SCOPE_PROMPT.format(input=user_input[:250])
            response = ollama.generate(
                model='llama3',
                prompt=prompt,
                options={
                    'temperature': 0.0,  # Maximum precision
                    'num_predict': 8,    # Short responses
                    'system': "You are an IT incident classifier."
                }
            )
            return 'yes' in response['response'].lower()

        except Exception:
            logger.exception("Scope classification failed")
            return True

    def handle_message(self, user_input, chat_history):
        try:
            clean_input = self._clean_user_input(user_input)

            if self.resolution_mode:
                return self._handle_resolution_response(clean_input)

            if self.ticket_mode:
                return self._process_ticket_creation(clean_input)

            # Scope validation with LLM
            if not self._is_it_related(clean_input):
                return (
                    "I can only assist with IT incidents!\n"
                    "Please describe technical issues such as:\n"
                    "- 'Cannot access VPN'\n"
                    "- 'System is slow'\n"
                    "- 'Email not syncing'\n"
                    "- 'Server is offline'"
                )

            # Starts ticket if within scope
            self._start_ticket_creation()
            self.ticket_data['description'] = clean_input
            self.current_step = 0
            return self._get_next_question()

        except Exception as e:
            logger.error(f"Error in handle_message: {e}", exc_info=True)
            return "I'm having trouble. Please try again."

    def _clean_user_input(self, user_input):
        cleaned = re.sub(r'\s+', ' ', user_input).strip()
        cleaned = re.sub(r'[^\w\s.,?!]', '', cleaned)
        return cleaned

    def _start_ticket_creation(self):
        self.ticket_mode = True
        self.ticket_data = {}
        logger.info("Ticket creation mode activated.")

    def _get_next_question(self):
        if self.current_step < len(self.required_steps):
            step_key = self.required_steps[self.current_step]
            return f"Registering a ticket. Please provide your {self.step_names[step_key]}:"
        return "Ready to create your ticket."

    def _process_ticket_creation(self, user_input):
        try:
            current_step_name = self.required_steps[self.current_step]

            if current_step_name == 'urgency':
                normalized_urgency = self._normalize_urgency(user_input)
                if normalized_urgency:
                    self.ticket_data[current_step_name] = normalized_urgency
                    self.current_step += 1
                else:
                    return "Please select: Low, Medium, High, or Critical."
            else:
                self.ticket_data[current_step_name] = user_input
                self.current_step += 1

            if self.current_step < len(self.required_steps):
                return self._get_next_question()
            return self._create_ticket()
        except Exception as e:
            logger.error(f"Ticket processing error: {e}", exc_info=True)
            return "Error. Let's restart."

    def _normalize_urgency(self, user_input):
        urgency_map = {
            'low': 'Low',
            'medium': 'Medium',
            'high': 'High',
            'critical': 'Critical',
            'urgent': 'High',
            'emergency': 'Critical',
            'normal': 'Medium',
            'priority': 'High'
        }
        lower_input = user_input.lower()
        for key, value in urgency_map.items():
            if key in lower_input:
                return value
        return None

    def _create_ticket(self):
        try:
            user_name = self.ticket_data['user_name']
            description = self.ticket_data['description']
            system = self.ticket_data['system']
            urgency = self.ticket_data['urgency']

            ticket_id = self.db.open_ticket(user_name, description, system, urgency)

            self.ticket_mode = False
            self.current_step = 0
            self.ticket_data = {}

            if ticket_id:
                self.active_ticket_id = ticket_id
                self.resolution_mode = True
                self.suggestion_count = 0
                self.suggestions = []

                # Buscar até 3 soluções do banco de dados
                db_suggestions = self._generate_db_suggestions(description, top_k=3)

                # Gerar sugestões da LLM apenas para completar 3 sugestões
                llm_needed = 3 - len(db_suggestions)
                if llm_needed > 0 and self.ollama_available:
                    for _ in range(llm_needed):
                        llm_suggestion = self._generate_llm_suggestion(description)
                        db_suggestions.append(llm_suggestion)

                # Se não encontrou nenhuma sugestão
                if not db_suggestions:
                    db_suggestions.append("No solutions found. Our team will contact you shortly.")

                # Verificar custos para cada sugestão
                for suggestion in db_suggestions:
                    has_cost = self._check_suggestion_cost(suggestion)
                    self.suggestions.append({
                        'text': suggestion,
                        'has_cost': has_cost
                    })

                return self._show_next_suggestion(ticket_id)
            return "❌ Failed to create ticket. Please contact support."
        except Exception as e:
            logger.error(f"Ticket creation error: {e}", exc_info=True)
            return "⚠️ Error creating ticket."

    def _generate_db_suggestions(self, problem_description, top_k=3):
        """Generate multiple solutions from closed tickets database"""
        similar_tickets = self.db.find_similar_tickets(problem_description, top_k=top_k)
        return [ticket['solution'] for ticket in similar_tickets if ticket.get('solution')]

    def _generate_llm_suggestion(self, problem_description):
        """Generate solution using LLM only"""
        try:
            response = ollama.generate(
                model='llama3',
                prompt=f"One simple solution for: {problem_description[:200]}",
                options={
                    'temperature': 0.2,
                    'num_predict': 60,
                    'system': "You are an IT support agent. Respond with one simple solution."
                }
            )
            return response['response']
        except:
            return "Please try restarting your device."

    def _check_suggestion_cost(self, suggestion):
        """Check if solution might incur costs to the customer using LLM"""
        if not self.ollama_available:
            return False  # Assume no cost if LLM unavailable

        try:
            prompt = (
                f"Does this IT solution potentially incur additional costs to the customer? "
                f"Answer only with 'YES' or 'NO'. Solution: {suggestion}"
            )

            response = ollama.generate(
                model='llama3',
                prompt=prompt,
                options={
                    'temperature': 0.1,
                    'num_predict': 10,
                    'system': "You are a cost analysis assistant. Be conservative - if unsure, say YES."
                }
            )

            # Parse response to get cost indication
            return "yes" in response['response'].lower()
        except Exception as e:
            logger.error(f"Cost check failed: {e}")
            return True  # Assume cost if check fails to be safe

    def _show_next_suggestion(self, ticket_id=None):
        """Show next suggestion to user with cost warning if needed"""
        if self.suggestion_count < len(self.suggestions):
            suggestion_data = self.suggestions[self.suggestion_count]
            suggestion = suggestion_data['text']
            cost_warning = "ATTENTION: This solution may generate additional costs.\n" if suggestion_data['has_cost'] else ""

            # Message for the first suggestion
            if self.suggestion_count == 0:
                return (
                    f"✅ Ticket #{ticket_id or self.active_ticket_id} created!\n\n"
                    f"{cost_warning}"
                    f"**Suggested solution:**\n"
                    f"{suggestion}\n\n"
                    f"Can we implement? (yes/no)"
                )

            # Message for the next suggestions
            return (
                f"{cost_warning}"
                f"**We can this instead (suggestion {self.suggestion_count + 1}/3):**\n"
                f"{suggestion}\n\n"
                f"Can we implement?"
            )
        return "Internal error: No suggestions available."

    #Delete this function after check
    def _db_suggestion_count(self):
        """Count how many suggestions came from database"""
        # Considera que as sugestões iniciais sempre vêm do banco
        return len(self.suggestions) - sum(1 for s in self.suggestions if "No solutions" in s or "AI" in s)

    def _handle_resolution_response(self, user_input):
        """Handle user response to suggested solution"""
        clean_input = user_input.lower().strip()

        if clean_input in ['yes', 'y']:
            # Close ticket with this solution
            solution = self.suggestions[self.suggestion_count]['text']
            #success = self.db.close_ticket(self.active_ticket_id, solution)
            self.db.update_Solu_open_ticket(self.active_ticket_id, solution)
            self.db.update_open_ticket(self.active_ticket_id, "Implemented Solution")
            self._reset_resolution_state()
            return "Great, we are implementing the solution! Close the ticket and contact us if needed."

        elif clean_input in ['no', 'n']:
            self.suggestion_count += 1

            # Limite de 3 sugestões
            if self.suggestion_count >= 3 or self.suggestion_count >= len(self.suggestions):
                self._reset_resolution_state()
                return (
                    "Our support team is now working on your issue. "
                    "We'll contact you shortly."
                )

            return self._show_next_suggestion()

        else:
            return "Please answer with 'yes' or 'no'."

    def _get_ticket_description(self):
        """Get ticket description from database"""
        if self.active_ticket_id:
            open_tickets = self.db.get_open_tickets()
            for ticket in open_tickets:
                if ticket['id'] == self.active_ticket_id:
                    return ticket['description']
        return "Technical issue"

    def _reset_resolution_state(self):
        self.resolution_mode = False
        self.active_ticket_id = None
        self.suggestions = []
        self.suggestion_count = 0


# Teste do fluxo com diferentes tipos de sugestões
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Starting smart suggestion flow test...")

    agent = IncidentAgent()
    responses = [
        "Cannot connect to VPN",
        "Ana Costa",
        "Cisco AnyConnect",
        "High",
        "no",  # Primeira sugestão (banco de dados) não funcionou
        "no",  # Segunda sugestão (LLM) não funcionou
        "no"   # Terceira sugestão (LLM) não funcionou -> Fecha automaticamente
    ]

    for user_input in responses:
        print(f"\nUser: {user_input}")
        response = agent.handle_message(user_input, [])
        print(f"Agent: {response}")
        time.sleep(1)

    logger.info("Test completed.")