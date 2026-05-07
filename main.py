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
    def setup_logging(self, log_file, level: int = logging.INFO):
        """
        Configura o logging exclusivamente para a aplicação.
        Bibliotecas de terceiros são silenciadas — apenas erros críticos aparecem.
        """
        fmt = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        root.handlers.clear()

        app_logger = logging.getLogger("app")
        app_logger.setLevel(level)
        app_logger.propagate = False
        app_logger.handlers.clear()

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(fmt)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

        app_logger.addHandler(file_handler)
        app_logger.addHandler(console_handler)

        app_logger.info("--- [ inicializado ] ---")

    def get_logger(self) -> logging.Logger:
        """Retorna o logger da aplicação."""
        return logging.getLogger("app")

    def check_and_update_log_file(self):
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"service_{dt.now().strftime('%Y-%m')}.log"

        app_logger = self.get_logger()
        if not log_file.exists() or not app_logger.hasHandlers():
            app_logger.info(f"Configurando novo arquivo de log: {log_file.name}")
            self.setup_logging(log_file)


log = Log().get_logger()


class Email:
    def __init__(
            self,
            para: Optional[List[str] | str] = None,
            titulo: str = "Sem Assunto",
            corpo_texto: Optional[str] = None,
    ) -> None:
        # Prefira variáveis de ambiente para não expor credenciais no código
        self._host = os.getenv("SMTP_HOST")
        self._port = int(os.getenv("SMTP_PORT"))
        self._user = os.getenv("SMTP_USER")
        self._password = os.getenv("SMTP_PASSWORD")

        if not para:
            raise ValueError("É necessário informar ao menos um destinatário.")

        self.para = [para] if isinstance(para, str) else para
        self.titulo = titulo
        self.corpo_texto = corpo_texto

        self.msg = MIMEMultipart()
        self._montar_cabecalho()
        self._montar_corpo()

    def _montar_cabecalho(self):
        self.msg['Date'] = formatdate(localtime=True)
        self.msg['From'] = self._user
        self.msg['Subject'] = self.titulo
        self.msg['To'] = ", ".join(self.para)

    def _montar_corpo(self):
        try:
            if self.corpo_texto:
                self.msg.attach(MIMEText(self.corpo_texto, 'plain'))
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
    def notify_error(error: Exception | str) -> None:
        """Envia um alerta por e-mail com os detalhes técnicos da falha."""
        detalhes_erro = (
            "".join(traceback.format_exception(None, error, error.__traceback__))
            if isinstance(error, Exception) else str(error)
        )

        corpo = (
            f"⚠️ ALERTA DE FALHA NA AUTOMAÇÃO AD\n"
            f"------------------------------------------\n"
            f"Data/Hora: {dt.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
            f"\nDetalhes Técnicos:\n"
            f"{detalhes_erro}\n"
            f"------------------------------------------\n"
            f"Favor verificar o servidor de automações."
        )
        try:
            Email(
                para=[
                    'pedrorodrigues@grupomonaco.com.br',
                    'silviomota@grupomonaco.com.br',
                    'lorramferreira@grupomonaco.com.br',
                ],
                titulo="🚨 ERRO CRÍTICO: Automação AD",
                corpo_texto=corpo,
            ).enviar()
            log.warning("Notificação de erro enviada.")
        except Exception as e:
            log.critical(f"Falha ao enviar e-mail de notificação de erro: {e}", exc_info=True)


class DBConnection:
    def __init__(self):
        # Prefira variáveis de ambiente
        self.DSN = os.getenv("DB_DSN")
        self.USER = os.getenv("DB_USER")
        self.PASSWORD = os.getenv("DB_PASSWORD")

    def get_inactive_users(self) -> list:
        """
        Retorna todos os usuários inativos no Metadados com data de rescisão.
        Utiliza context manager para garantir o fechamento da conexão.
        """
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
        """Retorna os logins (parte local do e-mail) de todos os usuários ativos."""
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
        self.LDAP_SERVER = os.getenv("LDAP_SERVER")
        self.LDAP_USER = os.getenv("LDAP_USER")
        self.LDAP_PASSWORD = os.getenv("LDAP_PASSWORD")
        self.GRUPO_DN = "CN=EMAIL_S4,OU=Usuarios,DC=grupomonaco,DC=local"
        self.BASE_DN = "DC=grupomonaco,DC=local"
        self.server = Server(self.LDAP_SERVER, get_info=ALL)

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
                    sam = u.sAMAccountName.value
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
    # Inicializa o sistema de logs
    Log().check_and_update_log_file()
    log.info("Iniciando automação AD...")

    try:
        db = DBConnection()
        users_inact = db.get_inactive_users()
        users_act = db.get_active_users()
        active_set = set(users_act)

        # Usuários sem nenhum contrato ativo e com rescisão há mais de 35 dias
        limite = dt.now() - timedelta(days=35)
        list_inactive = [
            u for u in users_inact
            if u[0] not in active_set and u[1] <= limite
        ]

        # Usuários desabilitados no AD que ainda estão no grupo
        manager = ManagerAD()
        ad_inactive = manager.get_inactive_users()

        inactive_logins = {list(u.keys())[0] for u in
                           [{u[0]: u[1]} for u in list_inactive]}

        # Usuários do AD estão na lista de inativos do Metadados
        to_remove = [
            entry for entry in ad_inactive
            if entry.sAMAccountName.value in inactive_logins
        ]

        manager.remove_users([])

        log.info("Automação AD concluída com sucesso.")

    except Exception as e:
        log.critical(f"Falha na automação: {e}", exc_info=True)
        Email.notify_error(e)


if __name__ == "__main__":
    main()
