document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    let chatHistory = [];

    // Adiciona mensagem inicial
    addMessage("Hi! I'm the Incident Management Assistant. How can I help you today? If you'd like to open a ticket, just ask.", false);

    // Função para adicionar mensagem ao chat
    function addMessage(text, isUser) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message');
        messageDiv.classList.add(isUser ? 'user-message' : 'bot-message');

        const infoDiv = document.createElement('div');
        infoDiv.classList.add('message-info');
        infoDiv.textContent = isUser ? 'Você' : 'AI Assistant';

        const textDiv = document.createElement('div');
        textDiv.textContent = text;

        messageDiv.appendChild(infoDiv);
        messageDiv.appendChild(textDiv);
        chatBox.appendChild(messageDiv);

        // Rolagem automática para o final
        chatBox.scrollTop = chatBox.scrollHeight;
        userInput.value = '';
    }

    // Função para enviar mensagem
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        // Adiciona mensagem do usuário
        addMessage(message, true);

        try {
            // Envia para o servidor
            const response = await fetch('/send_message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    history: chatHistory
                })
            });

            const data = await response.json();

            // Adiciona resposta do bot
            addMessage(data.response, false);

            // Atualiza histórico - CORREÇÃO IMPORTANTE!
            // Devemos adicionar a última interação (user + bot)
            chatHistory.push([message, data.response]);

        } catch (error) {
            console.error('Erro:', error);
            addMessage('Desculpe, ocorreu um erro ao processar sua solicitação.', false);
        }
    }

    // Event listeners
    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
});