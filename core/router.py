import difflib
import re


class IntentRouter:
    def __init__(self):
        self.routes = {}

    def register(self, keyword, module):
        self.routes[keyword.lower()] = module

    def dispatch(self, text):
        text_lower = text.lower().strip()
        if not text_lower:
            return None, None

        for keyword, module in self.routes.items():
            if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                return keyword, module

        words = re.findall(r"\b\w+\b", text_lower)
        for word in words:
            if len(word) < 3:
                continue
            close = difflib.get_close_matches(
                word, self.routes.keys(), n=1, cutoff=0.8
            )
            if close:
                return close[0], self.routes[close[0]]

        return None, None
