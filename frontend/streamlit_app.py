import os

import streamlit as st
from auth_pages import authenticate, manage_accounts
from customer_workspace import render_customer
from reviewer_dashboard import render_reviewer

from app.core.config import get_settings

st.title("SupportFlow AI")
url = st.sidebar.text_input("API URL", "http://localhost:8000")
local_session = None
if os.environ.get("SUPPORTFLOW_UI_AUTH_MODE", get_settings().auth_mode) == "local":
    local_session = authenticate(url)
    if not local_session:
        st.stop()
    if local_session["user"]["role"] == "admin":
        workspace = st.sidebar.radio("Workspace", ["Reviewer dashboard", "Manage accounts"])
        if workspace == "Manage accounts":
            manage_accounts(url, local_session)
        else:
            render_reviewer(url, True, local_session["access_token"])
        st.stop()
    mode, use_oidc = "Customer chat", True
else:
    mode = st.sidebar.radio("Workspace", ["Customer chat", "Reviewer dashboard"])
    use_oidc = st.sidebar.checkbox("Use OIDC access token", key="oidc_ui")
if mode == "Reviewer dashboard":
    render_reviewer(url, use_oidc)
    st.stop()
if local_session:
    key = local_session["access_token"]
    customer = local_session["user"]["id"]
    headers = {"Authorization": f"Bearer {key}"}
    if not local_session["user"]["email_verified"]:
        st.info(
            "Email is not verified yet. Verify it and log in again to enable automatic case emails."
        )
elif use_oidc:
    key = st.sidebar.text_input("Customer access token", type="password")
    customer = None
    headers = {"Authorization": f"Bearer {key}"}
else:
    key = st.sidebar.text_input("Demo API key", type="password")
    customer = st.sidebar.text_input("Customer ID", "demo-customer")
    headers = {"X-API-Key": key, "X-Customer-ID": customer}
render_customer(url, headers, (url, use_oidc, key, customer))
