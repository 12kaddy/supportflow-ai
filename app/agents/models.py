"""One model factory for chat, voice, and evaluations. No silent provider fallback."""

from app.core.config import get_settings


def model_identity():
    settings = get_settings()
    return {
        "provider": settings.llm_provider,
        "model": {
            "groq": settings.groq_model,
            "ollama": settings.ollama_model,
            "vllm": settings.vllm_model,
        }[settings.llm_provider],
    }


def build_model():
    settings = get_settings()
    common = {"temperature": 0, "timeout": settings.model_timeout}
    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        if not settings.groq_api_key:
            raise RuntimeError("Set GROQ_API_KEY for the Groq backend")
        return ChatGroq(
            model=settings.groq_model, api_key=settings.groq_api_key, max_retries=0, **common
        )
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            client_kwargs={"timeout": settings.model_timeout},
            num_predict=1024,
            num_ctx=8192,
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.vllm_model,
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key,
        max_retries=0,
        **common,
    )
