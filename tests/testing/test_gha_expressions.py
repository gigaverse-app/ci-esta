"""
Pin the GitHub Actions ``if:`` expression evaluator's semantics.

The evaluator exists so workflow tests can assert *decisions* against
synthetic event payloads instead of pinning expression strings. These tests
pin the GitHub-compatible semantics that make those decisions trustworthy:
operators return operands (not booleans), missing context reads are null,
and the supported grammar rejects what it cannot faithfully evaluate.
"""

import pytest

from ci_esta.testing.gha_expressions import (
    evaluate,
    evaluate_value,
    pull_request_event,
    schedule_event,
    workflow_dispatch_event,
)

PERF_LABEL = "perf"
LABELED_EXPRESSION = "github.event_name == 'pull_request' && contains(github.event.pull_request.labels.*.name, 'perf')"


class TestComparisonAndLiterals:
    def test_run_attempt_and_json_action_inputs(self) -> None:
        assert evaluate("github.run_attempt == 1", {"github": {"run_attempt": 1}})
        assert not evaluate("github.run_attempt == 1", {"github": {"run_attempt": 2}})
        assert evaluate_value("toJSON(fromJSON('[1,2]'))", {}) == "[1, 2]"

    def test_string_equality_matches_context_value(self) -> None:
        context = pull_request_event("opened")

        assert evaluate("github.event_name == 'pull_request'", context)
        assert not evaluate("github.event_name == 'push'", context)

    def test_inequality_is_the_negation_of_equality(self) -> None:
        context = pull_request_event("opened")

        assert evaluate("github.event_name != 'push'", context)
        assert not evaluate("github.event_name != 'pull_request'", context)

    def test_boolean_literals_evaluate_to_python_booleans(self) -> None:
        assert evaluate_value("true", {}) is True
        assert evaluate_value("false", {}) is False

    def test_missing_context_path_resolves_to_null(self) -> None:
        assert evaluate_value("github.event.label.name", schedule_event()) is None
        assert not evaluate("github.event.label.name == 'perf'", schedule_event())


class TestOperandReturningOperators:
    def test_and_or_chain_is_github_ternary(self) -> None:
        """
        `cond && 'a' || 'b'` selects a string, exactly like GitHub's
        docs."""
        selected = evaluate_value(
            "github.event_name == 'pull_request' && 'preview' || 'production'",
            pull_request_event("opened"),
        )
        fallback = evaluate_value(
            "github.event_name == 'pull_request' && 'preview' || 'production'",
            schedule_event(),
        )

        assert selected == "preview"
        assert fallback == "production"

    def test_or_returns_first_truthy_operand(self) -> None:
        context = workflow_dispatch_event(inputs={"reason": "manual"})

        assert evaluate_value("inputs.reason || 'default'", context) == "manual"
        assert evaluate_value("inputs.reason || 'default'", schedule_event()) == "default"

    def test_and_returns_left_operand_when_falsy(self) -> None:
        assert evaluate_value("false && 'never'", {}) is False

    def test_parentheses_group_before_and(self) -> None:
        context = pull_request_event("synchronize")

        assert evaluate(
            "(github.event_name == 'push' || github.event_name == 'pull_request')"
            " && github.event.action == 'synchronize'",
            context,
        )


class TestContains:
    def test_contains_matches_substring_of_string_operand(self) -> None:
        context = workflow_dispatch_event(inputs={"mode": "full-suite"})

        assert evaluate("contains(inputs.mode, 'full')", context)
        assert not evaluate("contains(inputs.mode, 'scoped')", context)

    def test_contains_over_label_object_filter(self) -> None:
        labeled = pull_request_event("synchronize", labels=[PERF_LABEL, "other"])
        unlabeled = pull_request_event("synchronize", labels=["other"])

        assert evaluate(LABELED_EXPRESSION, labeled)
        assert not evaluate(LABELED_EXPRESSION, unlabeled)

    def test_contains_on_null_sequence_is_false(self) -> None:
        assert not evaluate("contains(github.missing, 'x')", schedule_event())


class TestValueWrapper:
    def test_expression_wrapper_is_stripped(self) -> None:
        context = pull_request_event("opened")

        assert evaluate_value("${{ github.event_name == 'pull_request' && 'pr' || 'other' }}", context) == "pr"

    def test_bare_expression_needs_no_wrapper(self) -> None:
        assert evaluate_value("'plain'", {}) == "plain"


class TestRejectedInput:
    def test_untokenizable_input_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot tokenize"):
            evaluate("github.ref == $bad", {})

    def test_trailing_tokens_raise(self) -> None:
        with pytest.raises(ValueError, match="trailing tokens"):
            evaluate("true false", {})

    def test_unbalanced_parenthesis_raises(self) -> None:
        with pytest.raises(ValueError, match="expected"):
            evaluate("(true", {})

    def test_operator_without_operand_raises(self) -> None:
        with pytest.raises(ValueError, match="unexpected token"):
            evaluate("== 'x'", {})


class TestEventBuilders:
    def test_pull_request_event_carries_action_label_and_db_mode(self) -> None:
        context = pull_request_event("labeled", label=PERF_LABEL, db_mode="managed")

        assert evaluate("github.event.action == 'labeled'", context)
        assert evaluate("github.event.label.name == 'perf'", context)
        assert evaluate("steps.pr.outputs.db_mode == 'managed'", context)

    def test_workflow_dispatch_event_exposes_inputs(self) -> None:
        context = workflow_dispatch_event(inputs={"suite": "smoke"})

        assert evaluate("github.event_name == 'workflow_dispatch'", context)
        assert evaluate("inputs.suite == 'smoke'", context)

    def test_schedule_event_reads_every_input_as_null(self) -> None:
        context = schedule_event()

        assert evaluate("github.event_name == 'schedule'", context)
        assert evaluate_value("inputs.anything", context) is None
