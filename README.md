# Incident-Management-Chatbot
AI chatbot designed to automate incident management workflows, ticket routing, and provide intelligent IT support responses

1. Clone the repository
“git clone <repo_url>”
“cd incident_bot”

2. Create a virtual environment
“python -m venv .venv”
“source .venv/bin/activate”   # Linux/Mac
“.venv\Scripts\activate”      # Windows

3. Install dependencies
“pip install -r requirements.txt”

4. Install Ollama and Llama 3 locally
The chatbot requires Llama 3 to be available locally through Ollama.
Install Ollama following instructions at: https://ollama.ai/download


Pull the Llama 3 model locally:
“ollama pull llama3”
By default it will expose the API at http://localhost:11434.

5. Configure environment variables
Create a .env file in the project root with the following content:
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
PORT=0000

6. Start the Flask server
“python ChatBotInit.py”

7. Access the system in your browser
“http://127.0.0.1:YOUR-PORT”

