from flask import current_app
import anthropic
import os


class LLMCaller:
    MODEL = "claude-sonnet-4-6"
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

    def ask_question(self, context: str, question: str) -> str:
        system = (
            "You are a helpful personal assistant who answers general inquiries your manager has when reading. "
            "Provide clear answers which are as concise as possible."
        )
        user_content = f"Context: {context}\n\nQuestion: {question}"

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
