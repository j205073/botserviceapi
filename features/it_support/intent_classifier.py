import json
import os
from typing import Tuple, Optional


class ITIntentClassifier:
    """
    Lightweight intent classifier for IT issue categories based on keyword matching.
    Loads taxonomy.json and returns (code, label) for best match.
    """

    def __init__(self, taxonomy_path: Optional[str] = None):
        if taxonomy_path is None:
            taxonomy_path = os.path.join(os.path.dirname(__file__), "taxonomy.json")
        with open(taxonomy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.categories = data.get("categories", [])

    def classify(self, text: str) -> Tuple[str, str]:
        if not text:
            return ("other", self._label_for("other"))
        lower = text.lower()
        best = ("other", self._label_for("other"), 0)
        for c in self.categories:
            code = c.get("code", "other")
            label = c.get("label", code)
            keywords = c.get("keywords", [])
            score = 0
            for kw in keywords:
                if not kw:
                    continue
                # case-insensitive simple scoring
                if kw.lower() in lower:
                    score += 1
            if score > best[2]:
                best = (code, label, score)
        return (best[0], best[1])

    def _label_for(self, code: str) -> str:
        for c in self.categories:
            if c.get("code") == code:
                return c.get("label", code)
        return code

