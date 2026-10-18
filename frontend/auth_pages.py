"""Registration, login, verification, and admin account management."""

import time

import httpx
import streamlit as st


def request(url, method, path, body=None, token=None):
    try:
        response = httpx.request(
            method,
            url.rstrip("/") + "/v1/auth" + path,
            json=body,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=20,
        )
        if not response.is_success:
            detail = response.json().get("detail", "Request failed")
            st.error(
                detail
                if isinstance(detail, str)
                else "Check the form fields and password requirements."
            )
            return None
        return response.json()
    except (httpx.RequestError, ValueError):
        st.error("Unable to reach the account service.")
        return None


def authenticate(url):
    session = st.session_state.get("account_session")
    if session and (session["api_url"] != url or session["expires_at"] <= time.time()):
        st.session_state.pop("account_session", None)
        st.session_state.pop("history", None)
        session = None
    if session:
        st.sidebar.caption(f"{session['user']['name']} · {session['user']['role']}")
        if st.sidebar.button("Log out"):
            st.session_state.clear()
            st.rerun()
        return session
    page = st.radio("Account", ["Log in", "Register", "Verify email", "Resend verification"])
    with st.form("account_form", clear_on_submit=True):
        name = st.text_input("Full name") if page == "Register" else None
        email = st.text_input("Email")
        password = st.text_input("Password", type="password") if page != "Verify email" else None
        code = st.text_input("Verification code", max_chars=6) if page == "Verify email" else None
        if page == "Register":
            st.caption(
                "Use at least 12 characters for your password. Registration creates a customer account."
            )
        submit = st.form_submit_button(page)
    if submit:
        body = {"email": email, "password": password}
        if page == "Register":
            result = request(url, "POST", "/register", {**body, "name": name})
            if result:
                st.success("Account created. Check your email for a code, verify it, then log in.")
        elif page == "Log in":
            result = request(url, "POST", "/login", body)
            if result:
                st.session_state.account_session = {
                    **result,
                    "api_url": url,
                    "expires_at": time.time() + result["expires_in"],
                }
                st.rerun()
        elif page == "Verify email":
            if request(url, "POST", "/verify-email", {"email": email, "code": code}):
                st.success("Email verified. You can now log in.")
        elif request(url, "POST", "/resend-verification", body):
            st.success("Check your inbox for the verification code.")
    return None


def manage_accounts(url, session):
    st.header("Manage accounts")
    with st.form("admin_create_account", clear_on_submit=True):
        name = st.text_input("Name")
        email = st.text_input("Account email")
        password = st.text_input("Initial password", type="password")
        role = st.selectbox("Account role", ["customer", "admin"])
        submitted = st.form_submit_button("Create account")
    if submitted:
        result = request(
            url,
            "POST",
            "/admins" if role == "admin" else "/users",
            {"name": name, "email": email, "password": password},
            session["access_token"],
        )
        if result:
            st.success("Account created. A verification email is queued when email is enabled.")
    users = request(url, "GET", "/users", token=session["access_token"])
    if users:
        st.dataframe(users["items"], hide_index=True)
