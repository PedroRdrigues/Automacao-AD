import smtplib
import traceback
import logging
import os

from ldap3 import Server, Connection, ALL, MODIFY_DELETE
from oracledb import connect
from datetime import datetime as dt, timedelta
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import List, Optional
from base64 import b64encode
from dotenv import load_dotenv

load_dotenv(verbose=True)


class Log:
    _instance: "Log | None" = None

    def __new__(cls) -> "Log":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._session_handler = cls._SessionHandler()
            instance._logger = logging.getLogger("app")
            cls._instance = instance
        return cls._instance

    class _SessionHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self._records: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self._records.append(self.format(record))

        def get_text(self) -> str:
            return "\n".join(self._records)

    def setup_logging(self, log_file, level: int = logging.INFO) -> None:
        fmt = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        root.handlers.clear()

        self._logger.setLevel(level)
        self._logger.propagate = False
        self._logger.handlers.clear()

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(fmt)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

        self._session_handler.setFormatter(fmt)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)
        self._logger.addHandler(self._session_handler)

        self._logger.info("\n--- [ inicializado ] ---")

    def check_and_update_log_file(self) -> None:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"service_{dt.now().strftime('%Y-%m')}.log"

        if not log_file.exists() or not self._logger.hasHandlers():
            self.setup_logging(log_file)

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_session_log(self) -> str:
        return self._session_handler.get_text()


log = Log().get_logger()


class Email:
    def __init__(
            self,
            para: Optional[List[str] | str] = None,
            titulo: str = "Sem Assunto",
            corpo_texto: Optional[str] = None,
    ) -> None:
        self._host     = os.getenv("SMTP_HOST")
        self._port     = int(os.getenv("SMTP_PORT"))
        self._user     = os.getenv("SMTP_USER")
        self._password = os.getenv("SMTP_PASSWORD")

        if not para:
            raise ValueError("É necessário informar ao menos um destinatário.")

        self.para        = [para] if isinstance(para, str) else para
        self.titulo      = titulo
        self.corpo_texto = corpo_texto

        self.msg = MIMEMultipart()
        self._montar_cabecalho()
        self._montar_corpo()

    def _montar_cabecalho(self) -> None:
        self.msg['Date']    = formatdate(localtime=True)
        self.msg['From']    = self._user
        self.msg['Subject'] = self.titulo
        self.msg['To']      = ", ".join(self.para)

    def _montar_corpo(self) -> None:
        try:
            if self.corpo_texto:
                self.msg.attach(MIMEText(self.corpo_texto, 'plain', 'utf-8'))
        except Exception as e:
            log.error(f"Erro ao montar estrutura do e-mail: {e}")
            raise

    def enviar(self) -> bool:
        try:
            user_b64 = b64encode(self._user.encode('utf-8')).decode('ascii')
            pass_b64 = b64encode(self._password.encode('utf-8')).decode('ascii')

            with smtplib.SMTP_SSL(self._host, self._port) as server:
                server.ehlo()

                code, resp = server.docmd("AUTH", "LOGIN")
                if code != 334:
                    raise PermissionError(f"Servidor recusou AUTH LOGIN: {resp}")

                code, resp = server.docmd(user_b64)
                if code != 334:
                    raise PermissionError(f"Servidor recusou o usuário no AUTH LOGIN: {resp}")

                code, resp = server.docmd(pass_b64)
                if code != 235:
                    raise PermissionError(f"Autenticação recusada: {resp}")

                server.send_message(self.msg)

            log.info(f"E-mail '{self.titulo}' enviado para: {', '.join(self.para)}")
            return True

        except Exception as e:
            raise Exception(f"Falha crítica no envio de e-mail: {e}") from e

    @staticmethod
    def send_report(error: Optional[Exception] = None) -> None:
        sucesso      = error is None
        status_icon  = "✅" if sucesso else "❌"
        status_texto = "SUCESSO" if sucesso else "FALHA"
        data_hora    = dt.now().strftime('%d/%m/%Y %H:%M:%S')

        # Seção de erro — incluída apenas em caso de falha
        secao_erro = ""
        if error is not None:
            traceback_texto = "".join(
                traceback.format_exception(None, error, error.__traceback__)
            )
            secao_erro = (
                f"\nDETALHES DO ERRO:\n"
                f"------------------------------------------\n"
                f"{traceback_texto}"
                f"------------------------------------------\n"
            )

        corpo = (
            f"{status_icon} RELATÓRIO DE EXECUÇÃO — AUTOMAÇÃO AD\n"
            f"==========================================\n"
            f"Data/Hora : {data_hora}\n"
            f"Status    : {status_texto}\n"
            f"==========================================\n"
            f"{secao_erro}"
            f"\nLOG COMPLETO DA EXECUÇÃO:\n"
            f"------------------------------------------\n"
            f"{Log().get_session_log()}\n"
            f"------------------------------------------\n"
        )

        try:
            Email(
                para=os.getenv("EMAIL_RECIPIENTS_ERROR").split(";"),
                titulo=f"{status_icon} Automação AD — Relatório {dt.now().strftime('%d/%m/%Y')} [{status_texto}]",
                corpo_texto=corpo,
            ).enviar()
        except Exception as e:
            log.critical(f"Falha ao enviar relatório: {e}", exc_info=True)


class DBConnection:
    def __init__(self):
        self.DSN      = os.getenv("DB_DSN")
        self.USER     = os.getenv("DB_USER")
        self.PASSWORD = os.getenv("DB_PASSWORD")

    def get_inactive_users(self) -> list:
        """Retorna usuários inativos no Metadados com data de rescisão."""
        sql = """
            SELECT p.emailcorporativo, c.datarescisao
            FROM metadados.rhpessoas p
            JOIN metadados.rhcontratos c
              ON c.empresa = p.empresa AND c.pessoa = p.pessoa
            WHERE c.situacao = 4
              AND p.emailcorporativo IS NOT NULL
              AND c.datarescisao IS NOT NULL
        """
        with connect(user=self.USER, password=self.PASSWORD, dsn=self.DSN) as conn:
            with conn.cursor() as cursor:
                return [
                    [row[0].split('@')[0].strip(), row[1]]
                    for row in cursor.execute(sql)
                ]

    def get_active_users(self) -> list:
        """Retorna os logins de todos os usuários ativos."""
        sql = """
            SELECT p.emailcorporativo
            FROM metadados.rhpessoas p
            JOIN metadados.rhcontratos c
              ON c.empresa = p.empresa AND c.pessoa = p.pessoa
            WHERE c.situacao = 1
              AND p.emailcorporativo IS NOT NULL
        """
        with connect(user=self.USER, password=self.PASSWORD, dsn=self.DSN) as conn:
            with conn.cursor() as cursor:
                return [
                    row[0].split('@')[0].strip()
                    for row in cursor.execute(sql)
                ]


class ManagerAD:
    def __init__(self):
        self.LDAP_SERVER   = os.getenv("LDAP_SERVER")
        self.LDAP_USER     = os.getenv("LDAP_USER")
        self.LDAP_PASSWORD = os.getenv("LDAP_PASSWORD")
        self.GRUPO_DN      = "CN=EMAIL_S4,OU=Usuarios,DC=grupomonaco,DC=local"
        self.BASE_DN       = "DC=grupomonaco,DC=local"
        self.server        = Server(self.LDAP_SERVER, get_info=ALL)

    def get_inactive_users(self) -> list:
        """Retorna usuários desabilitados que ainda são membros do grupo de e-mail."""
        try:
            with Connection(self.server, user=self.LDAP_USER, password=self.LDAP_PASSWORD, auto_bind=True) as conn:
                log.info("Conectado com sucesso ao AD.")
                search_filter = (
                    f"(&(objectClass=user)"
                    f"(userAccountControl:1.2.840.113556.1.4.803:=2)"
                    f"(memberOf={self.GRUPO_DN}))"
                )
                conn.search(
                    search_base=self.BASE_DN,
                    search_filter=search_filter,
                    attributes=['distinguishedName', 'sAMAccountName'],
                )
                log.info("Busca por usuários inativos no grupo realizada com sucesso.")
                return conn.entries

        except Exception as e:
            raise Exception(f"Erro ao conectar/buscar no AD: {e}") from e

    def remove_users(self, usuarios: list) -> None:
        """Remove os usuários informados do grupo de e-mail."""
        if not usuarios:
            log.info("Nenhum usuário a remover do grupo.")
            return

        try:
            with Connection(self.server, user=self.LDAP_USER, password=self.LDAP_PASSWORD, auto_bind=True) as conn:
                log.info(f"Encontrados {len(usuarios)} usuário(s) para remoção.")

                for u in usuarios:
                    user_dn = u.distinguishedName.value
                    sam     = u.sAMAccountName.value
                    log.info(f"Removendo: {sam} ({user_dn})")

                    conn.modify(self.GRUPO_DN, {'member': [(MODIFY_DELETE, [user_dn])]})

                    if conn.result['description'] == 'success':
                        log.info(f"Sucesso: {sam} removido do grupo.")
                    else:
                        raise Exception(
                            f"Não foi possível remover {sam}: {conn.result['description']}"
                        )

        except Exception as e:
            raise Exception(f"Erro no processo de remoção de usuários do grupo: {e}") from e


def main() -> None:
    Log().check_and_update_log_file()
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
        log.info(f"{len(list_inactive)} usuário(s) inativo(s) elegíveis para remoção.")

        manager     = ManagerAD()
        ad_inactive = manager.get_inactive_users()

        inactive_logins = {u[0] for u in list_inactive}
        to_remove = [
            entry for entry in ad_inactive
            if entry.sAMAccountName.value in inactive_logins
        ]
        log.info(f"{len(to_remove)} usuário(s) serão removidos do grupo AD.")

        manager.remove_users(to_remove)
        log.info("Automação AD concluída com sucesso.")

    except Exception as e:
        error = e
        log.critical(f"Falha na automação: {e}", exc_info=True)

    finally:
        Email.send_report(error)


if __name__ == "__main__":
    main()