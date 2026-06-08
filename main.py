from datetime import timedelta, datetime as dt
from typing import Optional

from utils import Log, DBConnection, ManagerAD, Email
from s4 import S4EmailAutomation

Log().check_and_update_log_file()
log = Log().get_logger()
log.info("Iniciando automação AD...")

error: Optional[Exception] = None
try:
    db          = DBConnection()
    users_inact = db.get_inactive_users()
    users_act   = db.get_active_users()
    active_set  = set(users_act)

    limite = dt.now() - timedelta(days=35)
    list_inactive = [
        u for u in users_inact
        if u[0] not in active_set and u[1] <= limite
    ]

    manager     = ManagerAD()
    ad_inactive = manager.get_inactive_users()

    inactive_logins = {u[0] for u in list_inactive}
    to_remove = [
        entry for entry in ad_inactive
        if entry.sAMAccountName.value in inactive_logins
    ]

    manager.remove_users(to_remove)
    log.info("Automação AD concluída com sucesso.")

    log.info("Iniciando Automação S4.")

    automacao = S4EmailAutomation()
    try:
        automacao.realizar_login()
        automacao.acessar_menu_usuarios()
        automacao.processar_exclusoes()
    except Exception as e:
        print(f"💥 Ocorreu uma falha grave durante a execução: {e}")
    finally:
        automacao.fechar_driver()

    log.info("Automação S4 concluída com sucesso.")

except Exception as e:
    error = e
    log.critical(f"Falha na automação: {e}", exc_info=True)

finally:
    Email.send_report(error)
