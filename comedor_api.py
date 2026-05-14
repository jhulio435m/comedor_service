import json
from typing import Any

import requests


API_URL = "https://comensales.uncp.edu.pe/api/registros"


def build_payload(dni: str, codigo: str) -> dict[str, Any]:
    return {
        "t1_id": None,
        "t1_dni": dni,
        "t1_codigo": codigo,
        "t1_nombres": "",
        "t1_escuela": "",
        "t1_estado": None,
        "t3_periodos_t3_id": None,
    }


def post_registro(dni: str, codigo: str, timeout: int = 20) -> tuple[int, dict[str, Any]]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://comedor.uncp.edu.pe",
        "Referer": "https://comedor.uncp.edu.pe/",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
    }
    response = requests.post(
        API_URL,
        headers=headers,
        files={
            "data": (
                None,
                json.dumps(build_payload(dni, codigo), separators=(",", ":")),
                "application/json",
            )
        },
        timeout=timeout,
    )
    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text}
    response.raise_for_status()
    return response.status_code, data
