from flask import current_app
import anthropic
import os

class LLMCaller:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv('ANTHROPIC_API_KEY')
        )

    def ask_question(self, context: str, question: str) -> str:
        try:
            message = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.7,
                system="You are a helpful personal assistant who answers general inquiries your manager has when reading. Provide clear answers which are as concise as possible.",
                messages=[
                    {
                        "role": "user",
                        "content": f"Context: {context}\n\nQuestion: {question}"
                    }
                ]
            )
            return message.content[0].text
        except Exception as e:
            current_app.logger.error(f"Error calling Claude API: {str(e)}")
            return f"Sorry, I encountered an error: {str(e)}" 