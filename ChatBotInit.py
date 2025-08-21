from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask.cli import load_dotenv
from ollama_agent import IncidentAgent
from database import DatabaseManager
import logging
import json
import os

load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Inicializar componentes
try:
    db_manager = DatabaseManager()
    agent = IncidentAgent()

    # Populate initial data
    db_manager.populate_initial_data()
except Exception as e:
    logger.error(f"Critical initialization error: {e}", exc_info=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/open_tickets')
def open_tickets():
    tickets = db_manager.get_open_tickets()
    return render_template('open_tickets.html', tickets=tickets)

@app.route('/closed_tickets')
def closed_tickets():
    tickets = db_manager.get_closed_tickets()
    return render_template('closed_tickets.html', tickets=tickets)

@app.route('/close_ticket/<int:ticket_id>', methods=['POST'])
def close_ticket(ticket_id):
    solution = request.form['solution']
    success = db_manager.close_ticket(ticket_id, solution)
    if success:
        return redirect(url_for('open_tickets'))
    return "Ticket not found", 404

@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        data = request.json
        user_input = data['message']
        chat_history = data.get('history', [])

        response = agent.handle_message(user_input, chat_history)

        return jsonify({
            'response': response,
            'ticket_mode': agent.ticket_mode
        })
    except Exception as e:
        logger.error(f"Error in send_message: {e}", exc_info=True)
        return jsonify({'response': 'Sorry, an internal error occurred'}), 500

if __name__ == '__main__':

    app.run(debug=True, port=os.getenv('PORT'))