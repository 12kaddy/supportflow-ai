CUSTOMER = {"X-API-Key": "customer-secret", "X-Customer-ID": "alice"}
REVIEWER = {"X-Reviewer-Key": "reviewer-secret"}
APPROVE = {"decision": "approve", "reason": "Verified conflicting proof", "amount_cents": 10000}


async def create_case(http):
    response = await http.post(
        "/v1/cases", headers=CUSTOMER, json={"order_id": "order", "issue": "Not received"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
