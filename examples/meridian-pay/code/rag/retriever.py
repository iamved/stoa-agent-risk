"""Shared ticket + policy index. One index for all customers, no tenant filter."""
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

store = PineconeVectorStore(index_name="meridian-support-all", embedding=OpenAIEmbeddings())

def retrieve(query: str, k: int = 6):
    # TODO: filter by customer_id once verified identity is threaded through
    return store.similarity_search(query, k=k)
