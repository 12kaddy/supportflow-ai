"""Customer chat and email preferences, separate from account/workspace routing."""

import uuid

import httpx
import streamlit as st


def render_customer(url, headers, identity_context):
    st.link_button("Open voice support", url.rstrip("/") + "/v1/voice")
    with st.expander("Email preferences (optional)"):
        st.caption(
            "New cases automatically use your verified account email when SMTP is enabled. "
            "These controls let you opt out or manage local test addresses."
        )
        with st.form("email_updates"):
            email_case = st.text_input("Case ID", key="email_case_id")
            email_address = st.text_input(
                "Test email address (local mode only)", key="notification_address"
            )
            email_opt_in = st.checkbox("Enable status emails", key="email_opt_in")
            update_email = st.form_submit_button("Save email preference")
        if update_email:
            if not email_case.strip():
                st.error("Enter a case ID.")
            else:
                try:
                    response = httpx.put(
                        f"{url}/v1/cases/{email_case.strip()}/email-subscription",
                        json={"enabled": email_opt_in, "email": email_address or None},
                        headers=headers,
                        timeout=15,
                    )
                    if response.is_success:
                        st.success("Email preference saved.")
                    else:
                        st.error(
                            f"Unable to update email preference ({response.status_code}). Check API settings and case ownership."
                        )
                except httpx.RequestError:
                    st.error("Cannot reach the API.")
    context = identity_context
    if st.session_state.get("chat_identity_context") != context:
        st.session_state.chat_identity_context = context
        st.session_state.thread = str(uuid.uuid4())
        st.session_state.history = []
    if "thread" not in st.session_state:
        st.session_state.thread = str(uuid.uuid4())
    if "history" not in st.session_state:
        st.session_state.history = []
    for role, content in st.session_state.history:
        with st.chat_message(role):
            st.write(content)
    if prompt := st.chat_input("Ask about your order..."):
        st.session_state.history.append(("user", prompt))
        with st.chat_message("user"):
            st.write(prompt)
        try:
            response = httpx.post(
                f"{url}/v1/chat",
                json={"message": prompt, "thread_id": st.session_state.thread},
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            answer = response.json()["answer"]
        except Exception as exc:
            answer = f"Request failed: {exc}"
        st.session_state.history.append(("assistant", answer))
        with st.chat_message("assistant"):
            st.write(answer)
