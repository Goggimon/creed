from datetime import datetime


class Module:
    name = "system"
    intents = ["time", "date", "hello"]

    def __init__(self, lock):
        self.lock = lock

    def handle(self, intent, text, context):
        now = datetime.now()
        if intent == "time":
            return f"The current time is {now.strftime('%H:%M:%S')}."

        if intent == "date":
            return f"Today is {now.strftime('%A, %B %d, %Y')}."

        if intent == "hello":
            return "Hello."

        return None
