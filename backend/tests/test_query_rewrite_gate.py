"""The rewrite gate exists to stop a self-contained question paying for an
extra LLM call. On a free-tier key (Gemini: 20 requests/day) an unconditional
rewrite halves how many questions a user can actually ask.

It is deliberately biased towards rewriting: a false positive wastes one call,
a false negative searches with a query that's missing its referent and returns
the wrong chunks entirely.
"""

from app.services.agent import _needs_rewrite


class TestNeedsRewrite:
    def test_pronoun_reference_needs_history(self):
        assert _needs_rewrite("what about its payment terms?") is True
        assert _needs_rewrite("when does that expire") is True
        assert _needs_rewrite("who signed it") is True

    def test_followup_opener_needs_history(self):
        assert _needs_rewrite("what about the timeline") is True
        assert _needs_rewrite("and the overage rate") is True

    def test_terse_fragment_needs_history(self):
        # Too short to stand alone even without an obvious pronoun.
        assert _needs_rewrite("the timeline?") is True
        assert _needs_rewrite("renewal terms") is True

    def test_self_contained_question_skips_the_call(self):
        assert _needs_rewrite("What is the monthly hosting fee in the contract?") is False
        assert _needs_rewrite("How many weeks of parental leave does the policy grant?") is False

    def test_comparison_question_is_self_contained(self):
        assert (
            _needs_rewrite("Does the invoice match the contract on payment terms and overage rate?")
            is False
        )

    def test_punctuation_does_not_hide_a_pronoun(self):
        # "it." must still match after stripping trailing punctuation.
        assert _needs_rewrite("Please summarise the document and then explain it.") is True

    def test_case_is_ignored(self):
        assert _needs_rewrite("WHAT ABOUT THAT CLAUSE") is True

    def test_word_containing_a_token_is_not_a_false_match(self):
        # "their" is a token; "theirs"/"item" style substrings must not trip it.
        # This question is long and has no true pronoun, so it should skip.
        assert _needs_rewrite("Which itemised charges appear on the March invoice total?") is False

    def test_empty_query_is_treated_as_needing_context(self):
        assert _needs_rewrite("") is True
