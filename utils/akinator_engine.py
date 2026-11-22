"""20-questions deduction engine. Pure logic, no Discord.

Each character holds known yes/no traits. Unlisted traits are unknown. Every
answer reweights each character by how well it fits. The next question is the
one that splits the remaining probability most evenly among characters whose
trait is known. A guess is offered once one character is likely enough.
"""
from __future__ import annotations

ATTRIBUTES: dict[str, str] = {
    "has_fur": "Does it have fur?",
    "can_fly": "Can it fly?",
    "is_pet": "Is it commonly kept as a pet?",
    "lives_in_water": "Does it live mainly in water?",
    "is_mammal": "Is it a mammal?",
    "lays_eggs": "Does it lay eggs?",
    "is_bird": "Is it a bird?",
    "is_reptile": "Is it a reptile?",
    "eats_meat": "Does it eat meat?",
    "has_tail": "Does it have a tail?",
    "barks": "Does it bark?",
    "meows": "Does it meow?",
    "can_be_ridden": "Can people ride it?",
}

# True / False = known trait. A missing key means unknown.
CHARACTERS: dict[str, dict[str, bool]] = {
    "Cat": {"has_fur": True, "can_fly": False, "is_pet": True, "lives_in_water": False, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "eats_meat": True, "has_tail": True, "barks": False, "meows": True, "can_be_ridden": False},
    "Dog": {"has_fur": True, "can_fly": False, "is_pet": True, "lives_in_water": False, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "eats_meat": True, "has_tail": True, "barks": True, "meows": False},
    "Dolphin": {"has_fur": False, "can_fly": False, "is_pet": False, "lives_in_water": True, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "eats_meat": True, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Eagle": {"has_fur": False, "can_fly": True, "is_pet": False, "lives_in_water": False, "is_mammal": False, "lays_eggs": True, "is_bird": True, "is_reptile": False, "eats_meat": True, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Penguin": {"has_fur": False, "can_fly": False, "is_pet": False, "lives_in_water": True, "is_mammal": False, "lays_eggs": True, "is_bird": True, "is_reptile": False, "eats_meat": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Snake": {"has_fur": False, "can_fly": False, "is_mammal": False, "is_bird": False, "is_reptile": True, "eats_meat": True, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Turtle": {"has_fur": False, "can_fly": False, "is_mammal": False, "lays_eggs": True, "is_bird": False, "is_reptile": True, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Rabbit": {"has_fur": True, "can_fly": False, "is_pet": True, "lives_in_water": False, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "eats_meat": False, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Horse": {"has_fur": True, "can_fly": False, "lives_in_water": False, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "eats_meat": False, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": True},
    "Shark": {"has_fur": False, "can_fly": False, "is_pet": False, "lives_in_water": True, "is_mammal": False, "is_bird": False, "is_reptile": False, "eats_meat": True, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
    "Hamster": {"has_fur": True, "can_fly": False, "is_pet": True, "lives_in_water": False, "is_mammal": True, "lays_eggs": False, "is_bird": False, "is_reptile": False, "barks": False, "meows": False, "can_be_ridden": False},
    "Parrot": {"has_fur": False, "can_fly": True, "is_pet": True, "lives_in_water": False, "is_mammal": False, "lays_eggs": True, "is_bird": True, "is_reptile": False, "eats_meat": False, "has_tail": True, "barks": False, "meows": False, "can_be_ridden": False},
}

# Answer -> probability the answer is right when the trait is true. None = no information.
ANSWERS: dict[str, float | None] = {"yes": 0.95, "probably": 0.7, "dont_know": None, "probably_not": 0.3, "no": 0.05}
MAX_QUESTIONS = 20
GUESS_THRESHOLD = 0.85

_Snapshot = tuple[dict[str, float], list[str], set[str]]


class Game:
    def __init__(self, characters: dict[str, dict[str, bool]] | None = None, max_questions: int = MAX_QUESTIONS) -> None:
        self.characters = characters if characters is not None else CHARACTERS
        self.max_questions = max_questions
        self.weights: dict[str, float] = {name: 1.0 for name in self.characters}
        self.asked: list[str] = []
        self.rejected: set[str] = set()
        self._history: list[_Snapshot] = []

    def _alive(self) -> list[str]:
        return [n for n in self.characters if n not in self.rejected]

    def posterior(self) -> dict[str, float]:
        alive = self._alive()
        total = sum(self.weights[n] for n in alive)
        if not alive or total <= 0:
            return {}
        return {n: self.weights[n] / total for n in alive}

    def next_question(self) -> str | None:
        if len(self.asked) >= self.max_questions:
            return None
        post = self.posterior()
        best, best_score = None, 0.0
        for attr in ATTRIBUTES:
            if attr in self.asked:
                continue
            known = [(post[n], self.characters[n][attr]) for n in post if attr in self.characters[n]]
            mass = sum(p for p, _ in known)
            if mass <= 0:
                continue
            split = sum(p for p, v in known if v) / mass
            score = (1 - abs(split - 0.5) * 2) * mass
            if score > best_score:
                best, best_score = attr, score
        return best

    def answer(self, attr: str, answer: str) -> None:
        if answer not in ANSWERS:
            raise ValueError(f"unknown answer: {answer}")
        self._history.append((dict(self.weights), list(self.asked), set(self.rejected)))
        strength = ANSWERS[answer]
        if strength is not None:
            for n in self._alive():
                value = self.characters[n].get(attr)
                if value is None:
                    like = 0.5
                elif value:
                    like = strength
                else:
                    like = 1 - strength
                self.weights[n] *= like
            top = max((self.weights[n] for n in self._alive()), default=0.0)
            if top > 0:
                for n in self.weights:
                    self.weights[n] /= top  # keep numbers from underflowing
        self.asked.append(attr)

    def undo(self) -> bool:
        if not self._history:
            return False
        self.weights, self.asked, self.rejected = self._history.pop()
        return True

    def leader(self) -> tuple[str, float] | None:
        post = self.posterior()
        if not post:
            return None
        name = max(post, key=post.__getitem__)
        return name, post[name]

    def should_guess(self) -> bool:
        """Guess when confident, when the question budget is spent, or when no
        question would tell the remaining characters apart."""
        lead = self.leader()
        if lead is None:
            return False
        return (
            lead[1] >= GUESS_THRESHOLD
            or len(self.asked) >= self.max_questions
            or self.next_question() is None
        )

    def reject(self, name: str) -> None:
        self.rejected.add(name)
