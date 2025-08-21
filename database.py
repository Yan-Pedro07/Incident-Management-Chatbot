import random
import sqlite3
import json
import logging
import threading
import ollama
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        try:
            # Database for open tickets
            self.open_conn = sqlite3.connect('incidents_open.db', check_same_thread=False)
            self.open_conn.row_factory = sqlite3.Row

            # Database for closed tickets
            self.closed_conn = sqlite3.connect('incidents_closed.db', check_same_thread=False)
            self.closed_conn.row_factory = sqlite3.Row

            self._create_tables()
            self._generate_missing_embeddings()

            # List of listeners for ticket events
            self.ticket_listeners = []

            logger.info("DatabaseManager initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing DatabaseManager: {e}", exc_info=True)

    def add_ticket_listener(self, callback):
        """Add listener for ticket events"""
        self.ticket_listeners.append(callback)

    def _notify_listeners(self, event_type, ticket_data):
        """Notify all listeners about ticket events"""
        for listener in self.ticket_listeners:
            try:
                listener(event_type, ticket_data)
            except Exception as e:
                logger.error(f"Error notifying listener: {e}")

    def _create_tables(self):
        try:
            # Table for open tickets
            self.open_conn.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                description TEXT NOT NULL,
                system TEXT NOT NULL,
                urgency TEXT CHECK(urgency IN ('Low', 'Medium', 'High', 'Critical')) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                solution TEXT NOT NULL,
                status TEXT NOT NULL
            )
            ''')
            self.open_conn.commit()

            # Table for closed tickets
            self.closed_conn.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                user_name TEXT NOT NULL,
                description TEXT NOT NULL,
                system TEXT NOT NULL,
                urgency TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                solution TEXT NOT NULL,
                embedding TEXT,
                user_considerations TEXT,
                post_mortem TEXT
            )
            ''')
            self.closed_conn.commit()
            logger.info("Tables created successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}", exc_info=True)

    def _generate_missing_embeddings(self):
        """Generate embeddings for closed tickets that don't have them"""
        try:
            cursor = self.closed_conn.cursor()
            cursor.execute("SELECT id, description FROM tickets WHERE embedding IS NULL")
            tickets = cursor.fetchall()

            for ticket in tickets:
                try:
                    summary = self.summarize_description_solution(ticket['description'], ticket['solution'])
                    embedding = self._generate_embedding(summary)
                    if embedding:
                        embedding_json = json.dumps(embedding)
                        cursor.execute(
                            "UPDATE tickets SET embedding = ? WHERE id = ?",
                            (embedding_json, ticket['id'])
                        )
                        self.closed_conn.commit()
                        logger.info(f"Generated embedding for ticket {ticket['id']}")
                except Exception as e:
                    logger.error(f"Error generating embedding for ticket {ticket['id']}: {e}")
        except Exception as e:
            logger.error(f"Error generating missing embeddings: {e}", exc_info=True)

    def _generate_embedding(self, text):
        """Generate text embedding using Ollama"""
        try:
            if not text.strip():
                return []

            response = ollama.embeddings(model='nomic-embed-text', prompt=text)
            return response.get('embedding', [])
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return []

    def summarize_description_solution(self, description, solution):
        """Create a unified technical summary combining problem and solution"""
        try:
            response = ollama.generate(
                model='llama3',
                prompt=(
                    "Create a unified technical summary combining problem and solution. "
                    f"**Problem**: {description}\n"
                    f"**Solution**: {solution}\n\n"
                    "RULES:\n"
                    "- Maximum 2 sentences\n"
                    "- IT technical language\n"
                    "- Passive voice for actions\n"
                    "- No markdown or formatting\n"
                    "- English only\n"
                    "- Structure: [Problem] resolved via [Solution]"
                ),
                options={
                    'temperature': 0.2,
                    'num_predict': 120,
                    'stop': ["\n"]
                }
            )
            return response['response'].strip()

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"{description} resolved by {solution}"

    def post_mortem_analysis(self, description: str, solution: str, user_considerations: str) -> str:
        """Generate post-mortem analysis for a closed ticket"""
        try:
            logger.info("Starting post-mortem analysis...")

            prompt = (
                "## Post-Mortem Analysis Context\n"
                "You are an incident management specialist. Analyze the incident based on these elements:\n\n"
                f"**Incident Description:**\n{description}\n\n"
                f"**Applied Solution:**\n{solution}\n\n"
                f"**User Feedback:**\n{user_considerations}\n\n"
                "## Tasks:\n"
                "1. Identify root cause\n"
                "2. Assess user and business impact\n"
                "3. Analyze solution effectiveness\n"
                "4. Suggest preventive measures\n"
                "5. Assign criticality level (Low, Medium, High or Critical)\n\n"
                "## Response Format:\n"
                "- **Incident Summary:** [1 paragraph]\n"
                "- **Root Cause:** [Concise analysis]\n"
                "- **Impact Analysis:** [Actual/commercial effects]\n"
                "- **Solution Evaluation:** [Effectiveness and gaps]\n"
                "- **Preventive Measures:** [3-5 suggestions]\n"
                "- **Lessons Learned:** [2-3 key points]\n"
                "- **Criticality Level:** [Final classification with justification]\n"
            )

            response = ollama.generate(
                model='llama3',
                prompt=prompt,
                options={'temperature': 0.2}
            )

            logger.info("Post-mortem analysis generated successfully")
            return response['response']

        except Exception as e:
            logger.error(f"Error in post-mortem analysis: {e}", exc_info=True)
            return f"Error generating post-mortem analysis: {str(e)}"

    def open_ticket(self, user_name, description, system, urgency):
        try:
            cursor = self.open_conn.cursor()
            cursor.execute('''
            INSERT INTO tickets (user_name, description, system, urgency, solution, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_name, description, system, urgency, "-", "Working on a solution"))
            self.open_conn.commit()
            ticket_id = cursor.lastrowid

            # Buscar o ticket recém-criado para notificar
            cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
            ticket = cursor.fetchone()

            if ticket:
                ticket_data = dict(ticket)
                self._notify_listeners('opened', ticket_data)

            return ticket_id
        except Exception as e:
            logger.error(f"Error opening ticket: {e}", exc_info=True)
            return None

    def update_open_ticket(self, ticket_id, status):
        """Update the status of an open ticket"""
        try:
            cursor = self.open_conn.cursor()
            # Check if the ticket exists
            cursor.execute('SELECT id FROM tickets WHERE id = ?', (ticket_id,))
            if not cursor.fetchone():
                return False  # Ticket not found

            # Update ONLY the ticket status
            cursor.execute('''
                UPDATE tickets 
                SET status = ?
                WHERE id = ?
            ''', (status, ticket_id))

            self.open_conn.commit()
            logger.info("Ticket status updated")
            return True  # Success
        except Exception as e:
            logger.error(f"Error updating ticket status: {e}", exc_info=True)
            return False

    def update_Solu_open_ticket(self, ticket_id, solution):
        """Update the solution of an open ticket"""
        try:
            cursor = self.open_conn.cursor()
            # Check if the ticket exists
            cursor.execute('SELECT id FROM tickets WHERE id = ?', (ticket_id,))
            if not cursor.fetchone():
                return False  # Ticket not found

            # Update ONLY the solution
            cursor.execute('''
                UPDATE tickets 
                SET solution = ?
                WHERE id = ?
            ''', (solution, ticket_id))

            self.open_conn.commit()
            logger.info("Ticket solution updated")
            return True  # Success
        except Exception as e:
            logger.error(f"Error updating ticket solution: {e}", exc_info=True)
            return False

    def close_ticket(self, ticket_id, user_considerations):
        """Close a ticket and move it to the closed database"""
        try:
            # Get ticket from open database
            cursor = self.open_conn.cursor()
            cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
            ticket = cursor.fetchone()

            if not ticket:
                return False

            ticket_data = dict(ticket)

            # Generate embedding for description
            embedding = self._generate_embedding(ticket_data['description'])
            embedding_json = json.dumps(embedding) if embedding else None

            # Generate post-mortem analysis
            logger.info(f"Generating post-mortem analysis for ticket {ticket_id}")
            post_mortem = self.post_mortem_analysis(
                description=ticket_data['description'],
                solution=ticket_data['solution'],
                user_considerations=user_considerations
            )

            # Insert into closed database
            closed_cursor = self.closed_conn.cursor()
            closed_cursor.execute('''
            INSERT INTO tickets 
            (id, user_name, description, system, urgency, created_at, solution, embedding, user_considerations,
            post_mortem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ticket_data['id'],
                ticket_data['user_name'],
                ticket_data['description'],
                ticket_data['system'],
                ticket_data['urgency'],
                ticket_data['created_at'],
                ticket_data['solution'],
                embedding_json,
                user_considerations,
                post_mortem
            ))
            self.closed_conn.commit()

            # Remove from open database
            cursor.execute('DELETE FROM tickets WHERE id = ?', (ticket_id,))
            self.open_conn.commit()

            # Get the complete closed ticket for notification
            closed_cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_data['id'],))
            closed_ticket = closed_cursor.fetchone()

            if closed_ticket:
                closed_ticket_data = dict(closed_ticket)
                closed_ticket_data['closed_at'] = datetime.now().isoformat()
                self._notify_listeners('closed', closed_ticket_data)

            return True
        except Exception as e:
            logger.error(f"Error closing ticket: {e}", exc_info=True)
            return False

    def get_open_tickets(self):
        """Get all open tickets"""
        try:
            cursor = self.open_conn.cursor()
            cursor.execute('SELECT * FROM tickets ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching open tickets: {e}", exc_info=True)
            return []

    def get_closed_tickets(self):
        """Get all closed tickets"""
        try:
            cursor = self.closed_conn.cursor()
            cursor.execute('SELECT * FROM tickets ORDER BY closed_at DESC')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching closed tickets: {e}", exc_info=True)
            return []

    def find_similar_tickets(self, query_text, top_k=3, min_similarity=0.6):
        """Find closed tickets similar to the problem description"""
        try:
            # Generate embedding for query
            query_embedding = self._generate_embedding(query_text)
            if not query_embedding:
                return []

            # Get all closed tickets with valid embeddings
            cursor = self.closed_conn.cursor()
            cursor.execute("""
                SELECT id, user_name, description, system, urgency, 
                       created_at, closed_at, solution, embedding 
                FROM tickets 
                WHERE embedding IS NOT NULL
            """)
            tickets = [dict(row) for row in cursor.fetchall()]

            # Calculate similarity for each ticket
            similar_tickets = []
            for ticket in tickets:
                try:
                    ticket_embedding = json.loads(ticket['embedding'])
                    similarity = self._cosine_similarity(query_embedding, ticket_embedding)

                    if similarity >= min_similarity:
                        ticket['similarity'] = similarity
                        similar_tickets.append(ticket)
                except Exception as e:
                    logger.error(f"Error processing ticket {ticket['id']}: {e}")
                    continue

            # Sort by similarity (highest first)
            similar_tickets.sort(key=lambda x: x['similarity'], reverse=True)

            # Remove similarity field before returning
            for ticket in similar_tickets:
                if 'similarity' in ticket:
                    del ticket['similarity']

            return similar_tickets[:top_k]
        except Exception as e:
            logger.error(f"Error finding similar tickets: {e}", exc_info=True)
            return []

    def _cosine_similarity(self, a, b):
        """Calculate cosine similarity between two vectors"""
        try:
            # Ensure both inputs are lists of numbers
            if not (isinstance(a, list) and isinstance(b, list)):
                logger.error(f"Invalid input types for cosine similarity: {type(a)}, {type(b)}")
                return 0.0

            # Ensure both vectors have the same length
            if len(a) != len(b):
                logger.error(f"Vector length mismatch: {len(a)} vs {len(b)}")
                return 0.0

            dot_product = sum(float(x) * float(y) for x, y in zip(a, b))
            norm_a = sum(float(x) * float(x) for x in a) ** 0.5
            norm_b = sum(float(y) * float(y) for y in b) ** 0.5

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return dot_product / (norm_a * norm_b)
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    def populate_initial_data(self):
        """Populate databases with initial test data (only open tickets)"""
        try:
            # Check if data already exists
            if self.get_open_tickets():
                logger.info("Database already contains data. Skipping initial population.")
                return

            logger.info("Populating databases with initial data...")

            # Open tickets with solutions
            open_tickets = [
                {
                    "user_name": "Jennifer Lee",
                    "description": "Error saving document in Word",
                    "system": "Microsoft Word",
                    "urgency": "Medium",
                    "solution": "Check for available updates and install them",
                    "status": "In progress"
                },
                {
                    "user_name": "Thomas Moore",
                    "description": "VPN disconnects frequently",
                    "system": "Cisco AnyConnect",
                    "urgency": "High",
                    "solution": "Reinstall VPN client and update network drivers",
                    "status": "Pending"
                },
                {
                    "user_name": "Patricia Clark",
                    "description": "Windows update fails",
                    "system": "Windows Update",
                    "urgency": "Critical",
                    "solution": "Manually download updates and restart system",
                    "status": "Working on a solution"
                },
                {
                    "user_name": "James Taylor",
                    "description": "WiFi connection drops intermittently",
                    "system": "Ubuntu Network",
                    "urgency": "High",
                    "solution": "Update network drivers and check router settings",
                    "status": "Pending"
                },
                {
                    "user_name": "Elizabeth Hall",
                    "description": "Bluetooth not detecting devices",
                    "system": "Windows Bluetooth",
                    "urgency": "Medium",
                    "solution": "Check Bluetooth service and update drivers",
                    "status": "In progress"
                }
            ]

            # Insert open tickets directly
            cursor = self.open_conn.cursor()
            for ticket in open_tickets:
                try:
                    cursor.execute('''
                    INSERT INTO tickets (user_name, description, system, urgency, solution, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        ticket["user_name"],
                        ticket["description"],
                        ticket["system"],
                        ticket["urgency"],
                        ticket["solution"],
                        ticket["status"],
                        datetime.now() - timedelta(days=random.randint(1, 7))  # Random creation date in the past week
                    ))

                    # Notify listeners about the new ticket
                    ticket_id = cursor.lastrowid
                    cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
                    new_ticket = cursor.fetchone()

                    if new_ticket:
                        ticket_data = dict(new_ticket)
                        self._notify_listeners('opened', ticket_data)

                except Exception as e:
                    logger.error(f"Error inserting open ticket: {e}")

            self.open_conn.commit()
            logger.info(f"Database populated with {len(open_tickets)} open tickets")

        except Exception as e:
            logger.error(f"Error populating initial data: {e}", exc_info=True)


# Initialize database and populate with test data
if __name__ == "__main__":
    db = DatabaseManager()
    db.populate_initial_data()