import json

import httpx

from scripts import login


def test_device_login_uses_pkce_and_never_prints_tokens(tmp_path, monkeypatch, capsys):
    client_type = httpx.Client
    calls = []

    def respond(request):
        body = request.content.decode()
        calls.append(body)
        if request.url.path.endswith("/auth/device"):
            assert "code_challenge_method=S256" in body
            return httpx.Response(
                200,
                json={
                    "verification_uri_complete": "http://localhost:8080/device",
                    "user_code": "ABC",
                    "device_code": "private-device-code",
                    "interval": 1,
                    "expires_in": 30,
                },
            )
        assert "code_verifier=" in body
        return httpx.Response(
            200,
            json={
                "access_token": "private-access-token",
                "expires_in": 300,
                "refresh_token": "private-refresh-token",
            },
        )

    monkeypatch.setattr(
        login.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(login.time, "sleep", lambda seconds: None)
    output = tmp_path / "token.json"
    login.device_login("http://localhost:8080/realms/supportflow", output)
    assert json.loads(output.read_text()) == {
        "access_token": "private-access-token",
        "expires_in": 300,
    }
    assert "private-" not in capsys.readouterr().out
    assert len(calls) == 2
