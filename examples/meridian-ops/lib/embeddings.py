"""KB embeddings — intentionally NOT an agent."""
import os
from openai import OpenAI
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
def embed(texts):
    return client.embeddings.create(model="text-embedding-3-small", input=texts)
