"""Automatic per-message reasoning effort classification.

Pure rule-based (no LLM) — free, fast, deterministic.
Maps message complexity → reasoning effort each turn.
"""

from __future__ import annotations

import re
from typing import Literal

from hermes_constants import parse_reasoning_effort

# Effort levels exposed by the model API
EffortLevel = Literal["none", "minimal", "low", "medium", "high", "xhigh"]

# Keywords that strongly indicate complex/technical tasks
_COMPLEX_KEYWORDS = {
    # Code & debugging
    "debug", "debugging", "implement", "implementation", "refactor", "patch",
    "traceback", "stacktrace", "exception", "error", "bug", "fix", "broken",
    "codebase", "repository", "repo", "pull request", "merge", "commit",
    # Architecture & design
    "architecture", "design pattern", "system design", "scalability",
    "microservice", "api design", "schema", "refactor",
    # Analysis & research
    "analyze", "analysis", "investigate", "investigation", "research",
    "benchmark", "compare", "evaluate", "assess",
    # Planning & delegation
    "plan", "planning", "roadmap", "strategy", "delegate", "subagent",
    "agent", "workflow",
    # DevOps & infrastructure
    "docker", "kubernetes", "k8s", "ci/cd", "pipeline", "deployment",
    "infrastructure", "terraform", "ansible",
    # Data & ML
    "machine learning", "ml model", "training", "fine-tuning", "dataset",
    "neural network", "llm", "embedding", "vector",
    # Database
    "database", "migration", "schema", "sql", "query", "index",
    # Multi-step indicators
    "first", "then", "after that", "finally", "step", "steps",
    "multi", "multiple", "several things",
    # Tech stacks & frameworks
    "react", "node", "python", "javascript", "typescript", "golang", "rust",
    "django", "fastapi", "flask", "nextjs", "vue", "angular", "svelte",
    "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "api", "rest", "graphql", "grpc", "websocket",
    "frontend", "backend", "full-stack", "fullstack", "monolith",
    "microservice", "serverless", "lambda", "cloudflare",
    "github", "gitlab", "jenkins", "github actions", "vercel", "netlify",
    "docker compose", "kubernetes", "helm", "ingress", "load balancer",
}

# Keywords that indicate simple/purely conversational messages
_SIMPLE_KEYWORDS = {
    "hi", "hello", "hey", "thanks", "thank you", "please", "sorry",
    "what's up", "how are you", "good morning", "good evening",
    "good night", "bye", "goodbye", "lol", "haha", "cool", "nice",
    "okay", "ok", "sure", "yes", "no", "nope",
}

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```|`[^`]+`")
_QUESTION_RE = re.compile(r"\?")


class ReasoningClassifier:
    """Classifies message complexity and returns the appropriate reasoning config.

    Usage:
        classifier = ReasoningClassifier()
        result = classifier.classify("write me a function to add numbers")
        # → {"complexity": "moderate", "effort": "medium", "score": 0.4}
    """

    # Thresholds
    MAX_SIMPLE_CHARS = 40
    MAX_SIMPLE_WORDS = 10
    MAX_SIMPLE_NEWLINES = 0
    MAX_SIMPLE_CODE_BLOCKS = 0
    MAX_SIMPLE_URLS = 0

    # Score boundaries (0.0 – 1.0)
    #  0.0 – SIMPLE_THRESHOLD  → "simple"  → effort "none"
    #  SIMPLE_THRESHOLD – MODERATE_THRESHOLD → "moderate" → effort "medium"
    #  > MODERATE_THRESHOLD  → "complex" → effort "high"
    SIMPLE_THRESHOLD = 0.10
    MODERATE_THRESHOLD = 0.25

    # Effort mapping
    EFFORT_MAP = {
        "simple": "none",
        "moderate": "medium",
        "complex": "high",
    }

    def classify(self, text: str) -> dict:
        """Classify a message and return complexity + reasoning config.

        Returns:
            dict with keys:
                - complexity: "simple" | "moderate" | "complex"
                - effort: the effort level string
                - score: float 0.0–1.0 (raw complexity score)
                - reasons: list[str] of contributing factors
        """
        score, reasons = self._score(text)
        complexity = self._score_to_complexity(score)
        effort = self.EFFORT_MAP[complexity]
        config = parse_reasoning_effort(effort)
        return {
            "complexity": complexity,
            "effort": effort,
            "score": round(score, 3),
            "reasons": reasons,
            "config": config,
        }

    def _score(self, text: str) -> tuple[float, list[str]]:
        """Compute a 0.0–1.0 complexity score for the given text.

        Higher = more complex. Returns (score, list_of_factor_descriptions).
        """
        if not text or not text.strip():
            return 0.0, ["empty message"]

        score = 0.0
        reasons: list[str] = []

        # --- Length heuristics ---
        char_count = len(text)
        word_count = len(text.split())
        newline_count = text.count("\n")
        url_count = len(_URL_RE.findall(text))
        code_block_count = len(_CODE_BLOCK_RE.findall(text))
        question_count = len(_QUESTION_RE.findall(text))

        # Character count is a strong signal
        if char_count > 500:
            score += 0.25
            reasons.append(f"long text ({char_count} chars)")
        elif char_count > 200:
            score += 0.15
            reasons.append(f"medium text ({char_count} chars)")
        elif char_count > 100:
            score += 0.08
            reasons.append(f"moderate text ({char_count} chars)")

        # Word count
        if word_count > 100:
            score += 0.15
            reasons.append(f"high word count ({word_count} words)")
        elif word_count > 50:
            score += 0.08

        # Multi-line is a moderate signal (disagreement-style writing)
        if newline_count >= 3:
            score += 0.10
            reasons.append(f"multi-paragraph ({newline_count} newlines)")
        elif newline_count >= 1:
            score += 0.05

        # --- Structural signals ---
        if url_count >= 1:
            score += 0.10
            reasons.append(f"URL(s) present ({url_count})")

        if code_block_count >= 1:
            score += 0.20
            reasons.append(f"code block(s) ({code_block_count})")

        if question_count >= 2:
            score += 0.08
            reasons.append(f"multiple questions ({question_count})")

        # --- Keyword signals ---
        lowered = text.lower()

        # Pure conversational → likely simple (require word-boundary match)
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lowered) for kw in _SIMPLE_KEYWORDS):
            # Only count as simple signal if message is short
            if char_count < 80:
                score = max(score - 0.20, 0.0)
                reasons.append("conversational greeting/short reply")

        # Complex technical keywords
        found_complex = [kw for kw in _COMPLEX_KEYWORDS if kw in lowered]
        if found_complex:
            keyword_count = len(found_complex)
            score += min(0.05 * keyword_count, 0.25)
            reasons.append(f"complex keywords: {', '.join(found_complex[:5])}")

        # Multi-step/imperative lists
        multi_step_patterns = [
            r"\bfirst\b", r"\bthen\b", r"\blastly\b", r"\bfinally\b",
            r"\bafter that\b", r"\bstep \d\b", r"\bmulti\b",
            r"\band then\b", r"\bnext\b,?\s+(?:i'll|we'll|you)",
        ]
        if any(re.search(p, lowered) for p in multi_step_patterns):
            score += 0.12
            reasons.append("multi-step task detected")

        # Urgency/time pressure signals
        if any(w in lowered for w in ["urgent", "asap", "critical", "emergency", "important", "priority"]):
            score += 0.10
            reasons.append("priority signal")

        # Repeated periods or semicolons (lists/semicolon-separated clauses)
        semicolon_count = text.count(";") + text.count("•") + text.count("·")
        if semicolon_count >= 3:
            score += 0.08
            reasons.append("list-like structure")

        return min(score, 1.0), reasons

    def _score_to_complexity(self, score: float) -> str:
        if score < self.SIMPLE_THRESHOLD:
            return "simple"
        elif score < self.MODERATE_THRESHOLD:
            return "moderate"
        else:
            return "complex"


# ----------------------------------------------------------------------
# Convenience function
# ----------------------------------------------------------------------
_classifier = ReasoningClassifier()


def classify_message(text: str) -> dict:
    """One-shot classify + return reasoning config dict for AIAgent.

    Convenience wrapper around ReasoningClassifier().classify().
    """
    return _classifier.classify(text)
