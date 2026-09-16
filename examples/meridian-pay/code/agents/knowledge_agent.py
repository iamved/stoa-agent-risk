"""Knowledge agent: RAG over fee schedules, policies, and every customer's tickets."""
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState
from rag.retriever import retrieve

model = ChatOpenAI(model="gpt-4o", temperature=0.7)

def answer(state: MessagesState):
    q = state["messages"][-1].content
    docs = retrieve(q)
    context = "\n\n".join(d.page_content for d in docs)
    return {"messages": [model.invoke([("system", f"Answer from these documents only:\n{context}"), *state["messages"]])]}

graph = StateGraph(MessagesState)
graph.add_node("answer", answer)
graph.set_entry_point("answer")
knowledge = graph.compile()
