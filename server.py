#!/usr/bin/env python3
import threading
from http.server import ThreadingHTTPServer

from config import Config, parse_args
from http_api import make_handler
from runner import Runner
from store import Store, init_db
from telegram_bot import TelegramBot


def main() -> int:
    config = Config(parse_args())
    init_db(config.db_path)
    store = Store(config.db_path)
    runner = Runner(config, store)

    threading.Thread(target=runner.scheduler_loop, daemon=True).start()
    if config.telegram_bot_token:
        bot = TelegramBot(config, store, runner)
        runner.add_completion_callback(bot.send_run_report)
        threading.Thread(
            target=bot.polling_loop,
            daemon=True,
        ).start()
        if not config.telegram_admin_ids:
            print("Aviso: TELEGRAM_BOT_TOKEN esta configurado, pero TELEGRAM_ADMIN_IDS esta vacio.")

    server = ThreadingHTTPServer((config.host, config.port), make_handler(config, store, runner))
    print(
        f"Comedor service escuchando en http://{config.host}:{config.port} "
        f"y ejecutando cada dia a las {config.run_at} ({config.timezone.key})"
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
