from flask import current_app
import anthropic
import os
from typing import Optional


class LLMCaller:
    MODEL = "claude-3-5-sonnet-20241022"
    DEFAULT_TEMPERATURE = 0.7

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)

    def _call_api(
        self,
        system: str,
        user_content: str,
        max_tokens: int = 1000,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        try:
            message = self.client.messages.create(
                model=self.MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text
        except Exception as e:
            current_app.logger.error(f"Error calling Claude API: {str(e)}")
            return f"Sorry, I encountered an error: {str(e)}"

    def _should_search_context(self, context: str, question: str) -> bool:
        system = "You are an AI assistant that determines if additional context is needed to answer a question. Respond with 'Yes' or 'No' only."
        user_content = (
            f"Given this context and question, determine if additional information from the source material is needed to provide a complete answer.\n\n"
            f"Context:\n{context}\n\nQuestion:\n{question}\n\n"
        )

        response = self._call_api(
            system=system, user_content=user_content, max_tokens=100, temperature=0
        )
        return response.strip().lower() == "yes"

    def _search_additional_context(
        self, query: str, chapter_sentences: list[str]
    ) -> str:
        # TODO: investigate how to query relevant book context
        return ""

    def ask_question(
        self, context: str, question: str, chapter_sentences: Optional[list[str]] = None
    ) -> str:
        # First, determine if we need more context
        if self._should_search_context(context, question):
            # Get additional context if chapter_sentences were provided
            additional_context = ""
            if chapter_sentences:
                additional_context = self._search_additional_context(
                    question, chapter_sentences
                )

            # Combine original and additional context if found
            enhanced_context = context
            if additional_context:
                enhanced_context = (
                    f"{additional_context}\n\nHighlighted Text: {context}"
                )
        else:
            enhanced_context = context

        system = (
            "You are a helpful personal assistant who answers general inquiries your manager has when reading. "
            "Provide clear answers which are as concise as possible."
        )
        user_content = f"Context: {enhanced_context}\n\nQuestion: {question}"

        return self._call_api(system=system, user_content=user_content)

    def define_word(self, word: str, context: str) -> str:
        system = (
            "You are a helpful dictionary assistant. When given a word and its context, "
            "provide a clear, extremely concise definition that matches how the word is used in the context. "
        )
        user_content = f"Word: {word}\nContext: {context}\n\nDefinition: "

        return self._call_api(system=system, user_content=user_content, max_tokens=300)

    def translate_text(self, text: str, context: str) -> str:
        system = (
            "You are a helpful translation assistant. When given text and its context, "
            "translate the text to English. Only return the translation."
        )
        user_content = f"Text: {text}\nContext: {context}\n\nTranslation: "

        return self._call_api(system=system, user_content=user_content, max_tokens=300)
