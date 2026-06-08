# -*- coding: utf-8 -*-
"""
Orquestrador Principal - Automação de Desligamentos (AD e S4)
Este script centraliza a execução do pipeline de limpeza de usuários.
"""

from datetime import timedelta, datetime as dt
from typing import Optional

from utils import Log, DBConnection, ManagerAD, Email
from s4 import S4EmailAutomation

# Inicializa o log da sessão e atualiza o arquivo mensal
Log().check_and_update_log_file()
log = Log().get_logger()


def executar_pipeline():
    log.info("=== INICIANDO PIPELINE DE AUTOMAÇÃO DE DESLIGAMENTO ===")
    error: Optional[Exception] = None

    try:
        # ---------------------------------------------------------
        # ETAPA 1: Filtro de Regras de Negócio (Banco Oracle/ERP)
        # ---------------------------------------------------------
        log.info("Conectando ao banco de dados do RH para buscar status dos usuários...")
        db = DBConnection()
        users_inact = db.get_inactive_users()
        users_act = db.get_active_users()
        active_set = set(users_act)

        # Regra de negócio: Rescisão há mais de 35 dias e sem outro contrato ativo
        limite = dt.now() - timedelta(days=35)
        list_inactive = [
            u for u in users_inact
            if u[0] not in active_set and u[1] <= limite
        ]

        # ---------------------------------------------------------
        # ETAPA 2: Processamento no Active Directory
        # ---------------------------------------------------------
        log.info("Iniciando varredura no Active Directory...")
        manager = ManagerAD()
        ad_inactive = manager.get_inactive_users()

        inactive_logins = {u[0] for u in list_inactive}

        # Filtra quem está inativo no AD E também está na nossa lista de rescisão validada
        to_remove = [
            entry for entry in ad_inactive
            if entry.sAMAccountName.value in inactive_logins
        ]

        # Remove do grupo do AD e joga os logins afetados na memória RAM (SQLite)
        manager.remove_users(to_remove)
        log.info("Etapa de automação do Active Directory (AD) concluída.")

        # ---------------------------------------------------------
        # ETAPA 3: Automação Web no Portal S4 (Selenium)
        # ---------------------------------------------------------
        log.info("Iniciando Automação Web no Portal S4...")
        automacao = S4EmailAutomation()
        try:
            automacao.realizar_login()
            automacao.acessar_menu_usuarios()
            automacao.processar_exclusoes()
            automacao.fechar_s4()
        except Exception as e:
            raise Exception(f"Falha crítica durante a navegação web (Selenium): {e}") from e
        finally:
            automacao.fechar_driver()

        log.info("=== PIPELINE CONCLUÍDO COM SUCESSO ===")

    except Exception as e:
        error = e
        log.critical(f"A automação foi interrompida devido a uma falha: {e}", exc_info=True)

    finally:
        # Envia o relatório final com os logs anexados, independente de sucesso ou falha
        log.info("Gerando relatório operacional para envio por e-mail...")
        Email.send_report(error)


if __name__ == "__main__":
    executar_pipeline()