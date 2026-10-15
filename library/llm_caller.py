import os

import anthropic


class LLMError(Exception):
    """Raised when a Claude API call fails."""


class LLMCaller:
    MODEL = "claude-sonnet-4-6"
    DEFAULT_TEMPERATURE = 0.7

    def __init__(self):
        self._client = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

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
        except anthropic.AnthropicError as e:
            raise LLMError(str(e)) from e
        return message.content[0].text

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

    def explain(self, text: str, context: str) -> str:
        """One action for "what does this mean?": defines a word, translates
        foreign text, or glosses a passage, depending on what was selected."""
        system = (
            "You help someone reading a book understand a selection. Look at the "
            "selected text and its surrounding context, then do exactly one of:\n"
            "- If it is not in English: give the English translation, then a "
            "short note on anything a translation loses.\n"
            "- If it is a single word or short phrase in English: define it as it "
            "is used here, in one or two sentences.\n"
            "- If it is a longer English passage: explain what it means and any "
            "reference or allusion a reader might miss, in at most three sentences.\n"
            "No preamble, no restating the selection."
        )
        user_content = f"Selection: {text}\nContext: {context}"
        return self._call_api(system=system, user_content=user_content, max_tokens=400)

