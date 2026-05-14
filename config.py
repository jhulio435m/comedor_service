import argparse
import os
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_DB = Path(__file__).with_name("comedor.db")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_TZ = "America/Lima"
DEFAULT_RUN_AT = "07:00"
DEFAULT_RETRY_SECONDS = 60
DEFAULT_START_BEFORE_MINUTES = 0
DEFAULT_STOP_AFTER_MINUTES = 1


def parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            ids.add(int(item))
    return ids


class Config:
    def __init__(self, args: argparse.Namespace) -> None:
        self.db_path = Path(args.db)
        self.host = args.host
        self.port = args.port
        self.timezone = ZoneInfo(args.timezone)
        self.run_at = args.run_at
        self.retry_seconds = args.retry_seconds
        self.start_before_minutes = args.start_before_minutes
        self.stop_after_minutes = args.stop_after_minutes
        self.admin_token = args.admin_token or os.environ.get("COMEDOR_ADMIN_TOKEN", "")
        self.telegram_bot_token = args.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_admin_ids = parse_admin_ids(
            args.telegram_admin_ids or os.environ.get("TELEGRAM_ADMIN_IDS", "")
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Servicio diario para registros de comedor.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta de la base SQLite")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host del servidor HTTP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto del servidor HTTP")
    parser.add_argument("--timezone", default=DEFAULT_TZ, help="Zona horaria del scheduler")
    parser.add_argument("--run-at", default=DEFAULT_RUN_AT, help="Hora diaria HH:MM")
    parser.add_argument("--retry-seconds", type=int, default=DEFAULT_RETRY_SECONDS)
    parser.add_argument(
        "--start-before-minutes",
        type=int,
        default=DEFAULT_START_BEFORE_MINUTES,
        help="Minutos antes de --run-at para empezar a intentar",
    )
    parser.add_argument(
        "--stop-after-minutes",
        type=int,
        default=DEFAULT_STOP_AFTER_MINUTES,
        help="Minutos despues de --run-at para dejar de intentar",
    )
    parser.add_argument("--admin-token", default="", help="Token admin, mejor usar COMEDOR_ADMIN_TOKEN")
    parser.add_argument("--telegram-bot-token", default="", help="Token del bot, mejor usar TELEGRAM_BOT_TOKEN")
    parser.add_argument("--telegram-admin-ids", default="", help="IDs Telegram autorizados, separados por coma")
    return parser.parse_args()
