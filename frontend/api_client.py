"""Small reviewer API client; no Streamlit state or cached credentials."""

from urllib.parse import quote

import httpx


class ApiError(Exception):
    pass


class ReviewerClient:
    def __init__(self, url, key, bearer=False):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}"} if bearer else {"X-Reviewer-Key": key}

    def request(self, method, path, **kwargs):
        try:
            response = httpx.request(
                method,
                self.url + "/v1/reviewer/cases" + path,
                headers=self.headers,
                timeout=15,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", "Request failed")
            except ValueError:
                detail = "Request failed"
            raise ApiError(f"{exc.response.status_code}: {detail}") from None
        except httpx.RequestError:
            raise ApiError(
                "Cannot reach the API. Check its URL and whether it is running."
            ) from None
        return response.json()

    def cases(self, status, offset=0):
        params = {"offset": offset, "limit": 25}
        if status != "all":
            params["status"] = status
        return self.request("GET", "", params=params)

    def case(self, case_id):
        return self.request("GET", "/" + quote(case_id, safe=""))

    def audit(self, case_id):
        return self.request("GET", "/" + quote(case_id, safe="") + "/audit")

    def similar(self, case_id):
        return self.request("GET", "/" + quote(case_id, safe="") + "/similar")

    def review(self, case_id, decision, reason, amount):
        return self.request(
            "POST",
            "/" + quote(case_id, safe="") + "/review",
            json={
                "decision": decision,
                "reason": reason,
                "amount_cents": amount if decision == "approve" else None,
            },
        )

    def execute(self, case_id):
        return self.request("POST", "/" + quote(case_id, safe="") + "/execute")
