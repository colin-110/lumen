"""Tenant isolation.

Every retrieval path filters Qdrant by organization (or by owner for users
with no org). If that condition were ever dropped, weakened, or *replaced* by
a caller-controlled one, one tenant's questions would retrieve another
tenant's documents — the worst failure this system can have, and a silent one:
answers would still look plausible.

These assert the filter's shape directly rather than going through Qdrant, so
they run in CI with no services and fail loudly the moment the guarantee is
edited away.
"""

from qdrant_client.http import models

from app.services.retrieval import _tenant_filter

ORG = "11111111-1111-1111-1111-111111111111"
OWNER = "22222222-2222-2222-2222-222222222222"
OTHER_ORG = "33333333-3333-3333-3333-333333333333"


def conditions(f: models.Filter) -> list:
    return list(f.must or [])


def keys(f: models.Filter) -> list[str]:
    return [c.key for c in conditions(f)]


class TestScopeIsAlwaysApplied:
    def test_org_member_is_scoped_to_their_organization(self):
        f = _tenant_filter(ORG, OWNER)
        assert "organization_id" in keys(f)
        match = next(c for c in conditions(f) if c.key == "organization_id")
        assert match.match.value == ORG

    def test_user_without_an_org_is_scoped_to_themselves(self):
        f = _tenant_filter(None, OWNER)
        assert "owner_id" in keys(f)
        match = next(c for c in conditions(f) if c.key == "owner_id")
        assert match.match.value == OWNER

    def test_org_scope_takes_precedence_over_owner_scope(self):
        # Documents are shared within an org, so org membership is the boundary.
        # Both conditions together would hide a colleague's documents.
        f = _tenant_filter(ORG, OWNER)
        assert "owner_id" not in keys(f)

    def test_filter_is_never_empty(self):
        # An empty `must` matches every point in the collection.
        for org in (ORG, None):
            assert conditions(_tenant_filter(org, OWNER)), "unscoped filter would match all tenants"


class TestDocumentPinningCannotEscapeTheTenant:
    """`document_ids` comes from the request body, so it is attacker-controlled.
    It must narrow the tenant scope, never replace it."""

    def test_pinned_ids_are_added_to_the_tenant_scope_not_substituted(self):
        f = _tenant_filter(ORG, OWNER, ["doc-a", "doc-b"])
        assert "organization_id" in keys(f), "tenant condition dropped when documents were pinned"
        assert "document_id" in keys(f)

    def test_pinning_another_tenants_document_still_requires_the_org_match(self):
        # Qdrant ANDs `must`, so a foreign document_id yields no points rather
        # than leaking one.
        f = _tenant_filter(ORG, OWNER, ["a-document-belonging-to-another-org"])
        org_cond = next(c for c in conditions(f) if c.key == "organization_id")
        assert org_cond.match.value == ORG
        assert org_cond.match.value != OTHER_ORG

    def test_ownerless_user_pinning_documents_stays_owner_scoped(self):
        f = _tenant_filter(None, OWNER, ["doc-a"])
        assert "owner_id" in keys(f)
        assert "document_id" in keys(f)

    def test_empty_or_none_document_ids_do_not_add_a_condition(self):
        for ids in (None, []):
            f = _tenant_filter(ORG, OWNER, ids)
            assert "document_id" not in keys(f)
            assert "organization_id" in keys(f)

    def test_pinned_ids_are_matched_as_a_set_not_concatenated(self):
        f = _tenant_filter(ORG, OWNER, ["a", "b", "c"])
        doc_cond = next(c for c in conditions(f) if c.key == "document_id")
        assert set(doc_cond.match.any) == {"a", "b", "c"}


class TestEveryRetrievalEntryPointIsScoped:
    def test_all_search_variants_require_tenant_arguments(self):
        # A variant that defaulted its tenant arguments could be called without
        # a scope and would search the whole collection.
        import inspect

        from app.services import retrieval

        for name in (
            "hybrid_search",
            "dense_search",
            "sparse_search",
            "hybrid_search_no_rerank",
            "hybrid_search_reranked",
        ):
            sig = inspect.signature(getattr(retrieval, name))
            for param in ("organization_id", "owner_id"):
                assert param in sig.parameters, f"{name} has no {param}"
                assert (
                    sig.parameters[param].default is inspect.Parameter.empty
                ), f"{name}.{param} has a default; it could be called unscoped"
