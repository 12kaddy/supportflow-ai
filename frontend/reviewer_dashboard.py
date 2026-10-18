"""Reviewer UI. Backend services remain responsible for all authorization."""

import streamlit as st
from api_client import ApiError, ReviewerClient


def render_reviewer(url, use_oidc=False, access_token=None):
    st.header("Resolution review")
    label = "Reviewer access token" if use_oidc else "Reviewer key"
    key = access_token or st.sidebar.text_input(
        label, type="password", key="reviewer_token" if use_oidc else "reviewer_key"
    )
    if not key:
        st.info(f"Enter your {label.lower()} to load cases.")
        return
    client = ReviewerClient(url, key, True) if use_oidc else ReviewerClient(url, key)
    status = st.selectbox(
        "Case status",
        ["awaiting_review", "awaiting_investigation", "approved", "resolved", "rejected", "all"],
    )
    page = st.number_input("Page", min_value=1, step=1, value=1)
    st.button("Refresh")
    try:
        result = client.cases(status, (page - 1) * 25)
        if not result["items"]:
            st.info("No cases on this page.")
            return
        items = {case["id"]: case for case in result["items"]}
        case_id = st.selectbox(
            "Case",
            list(items),
            format_func=lambda value: (
                f"{items[value]['order_id']} · {value} · {items[value]['status']}"
            ),
        )
        if result["has_more"]:
            st.caption("More cases are available on the next page.")
        case = client.case(case_id)
        events = client.audit(case_id)["events"]
        render_case(client, case)
        render_similar_cases(client, case_id)
        st.subheader("Audit history")
        for event in events:
            with st.expander(f"{event['kind']} · {event['actor']} · {event['created_at']}"):
                st.json(event["details"])
    except ApiError as exc:
        st.error(str(exc))


def render_similar_cases(client, case_id):
    with st.expander("Similar simulated resolutions"):
        try:
            result = client.similar(case_id)
        except ApiError as exc:
            st.warning(f"Similar-case suggestions are unavailable: {exc}")
            return
        st.caption(result["notice"])
        if not result["items"]:
            st.info(
                "No comparable reviewed simulations found. Continue using the current evidence and policy."
            )
        for item in result["items"]:
            st.write(f"**Reference case:** {item['reference_case_id']}")
            st.caption(
                f"Feature match: {item['similarity_score']:.0%} (not outcome probability) · Outcome: simulated refund · "
                f"Policy: {item['policy_version']}"
            )
            st.write("Matching features: " + ", ".join(item["matching_features"]))
            if item["differences"]:
                st.json(item["differences"])
        if result["candidate_pool_truncated"]:
            st.caption("Suggestions consider only the 200 most recent eligible simulations.")


def render_case(client, case):
    st.subheader(f"Order {case['order_id']}")
    st.caption(f"Customer: {case['customer_id']} · Status: {case['status']}")
    st.text(case["issue"])
    investigation = case["investigation"]
    decision = investigation["decision"]
    st.write("**Proposed action:**", decision["action"])
    st.text(decision["reason"])
    st.caption(f"Policy: {decision['policy_version']} · {decision['policy_source']}")
    if decision["missing_information"]:
        st.warning("Missing information: " + ", ".join(decision["missing_information"]))
    with st.expander("Evidence snapshot", expanded=True):
        st.json({name: investigation[name] for name in ["order", "delivery", "previous_case_ids"]})
    if case["review"]:
        st.write("**Recorded review**")
        st.json(case["review"])
    if case["status"] in {"awaiting_review", "awaiting_investigation"}:
        render_review_form(client, case, decision)
    elif case["status"] == "approved":
        confirmed = st.checkbox("Confirm simulated refund execution", key=f"confirm_{case['id']}")
        if st.button("Execute simulated refund", disabled=not confirmed):
            client.execute(case["id"])
            st.rerun()
    elif case["status"] == "resolved":
        st.success("Resolved with a simulated refund. No money was moved.")


def render_review_form(client, case, decision):
    eligible = decision["action"] == "refund_review"
    choices = ["reject", "approve"] if eligible else ["reject"]
    if not eligible:
        st.info("This proposal does not support refund approval.")
    with st.form(f"review_{case['id']}"):
        action = st.selectbox("Review decision", choices)
        reason = st.text_area("Reason", max_chars=2000)
        amount = st.number_input(
            "Approved amount (minor units; used only for approval)",
            min_value=1,
            value=max(1, case["investigation"]["order"]["amount_cents"]),
            step=1,
        )
        submitted = st.form_submit_button("Record review")
    if submitted:
        if not reason.strip():
            st.error("A review reason is required.")
            return
        client.review(case["id"], action, reason, amount)
        st.rerun()
