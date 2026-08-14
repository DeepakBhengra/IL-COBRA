from fastapi.testclient import TestClient
from cobol_error_scanner.api.server import create_app
c = TestClient(create_app())
r = c.post("/api/findings/0/confirmed-resolution?out_dir=out", json={"selected_text": "t", "comment": "c", "source": "historical"})
print("status", r.status_code)
print(r.text[:400])
