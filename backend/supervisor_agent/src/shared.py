import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# Shared Configuration
DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable"

# Initializing LLM for the Supervisor
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.0,
    api_key=os.getenv("GROQ_API_KEY"),
)
