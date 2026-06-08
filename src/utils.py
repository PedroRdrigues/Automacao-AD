# -*- coding: utf-8 -*-
"""
Utilitários Centrais
Contém classes para Logging, Notificação por E-mail, Conexão AD e Bancos de Dados (Oracle/SQLite).
"""

import sqlite3
import smtplib
import traceback
import logging
import os

from ldap3 import Server, Connection, ALL, MODIFY_DELETE
from oracledb import connect
from datetime import datetime as dt
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import List, Optional
from base64 import b64encode
from dotenv import load_dotenv

load_dotenv(verbose=True)


class Log:
    """Implementa o padrão Singleton para gerenciamento centralizado de logs."""
    _instance: "Log | None" = None

    def __new__(cls) -> "Log":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._session_handler = cls._SessionHandler()
            instance._logger = logging.getLogger("app_automacao")
            cls._instance = instance
        return cls._instance

    class _SessionHandler(logging.Handler):
        """Handler customizado que guarda os logs na memória para enviar por e-mail no final."""

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

        self._logger.setLevel(level)
        self._logger.propagate = False
        self._logger.handlers.clear()

        # Log no arquivo local
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(fmt)

        # Log no terminal (console)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

        # Log de sessão (para o e-mail)
        self._session_handler.setFormatter(fmt)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)
        self._logger.addHandler(self._session_handler)

    def check_and_update_log_file(self) -> None:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"automacao_ad_{dt.now().strftime('%Y-%m')}.log"

        if not log_file.exists() or not self._logger.hasHandlers():
            self.setup_logging(log_file)

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_session_log(self) -> str:
        return self._session_handler.get_text()


# Instância global facilitadora de Log para uso interno no utils
log = Log().get_logger()


class Email:
    """Gerencia notificações operacionais via e-mail SMTP Autenticado."""

    def __init__(self, para: Optional[List[str] | str] = None, titulo: str = "Sem Assunto",
                 corpo_texto: Optional[str] = None) -> None:
        self._host = os.getenv("SMTP_HOST")
        self._port = int(os.getenv("SMTP_PORT", "465"))
        self._user = os.getenv("SMTP_USER")
        self._pass = os.getenv("SMTP_PASSWORD")

        if not para:
            raise ValueError("É obrigatório informar ao menos um destinatário no e-mail.")

        self.para = [para] if isinstance(para, str) else para
        self.titulo = titulo
        self.corpo_texto = corpo_texto

        self.msg = MIMEMultipart()
        self._montar_cabecalho()
        self._montar_corpo()

    def _montar_cabecalho(self) -> None:
        self.msg['Date'] = formatdate(localtime=True)
        self.msg['From'] = self._user
        self.msg['Subject'] = self.titulo
        self.msg['To'] = ", ".join(self.para)

    def _montar_corpo(self) -> None:
        if self.corpo_texto:
            self.msg.attach(MIMEText(self.corpo_texto, 'plain', 'utf-8'))

    def enviar(self) -> bool:
        try:
            user_b64 = b64encode(self._user.encode('utf-8')).decode('ascii')
            pass_b64 = b64encode(self._pass.encode('utf-8')).decode('ascii')

            with smtplib.SMTP_SSL(self._host, self._port) as server:
                server.ehlo()

                # Autenticação manual segura em Base64
                code, resp = server.docmd("AUTH", "LOGIN")
                if code != 334: raise PermissionError(f"Servidor recusou AUTH LOGIN: {resp}")

                code, resp = server.docmd(user_b64)
                if code != 334: raise PermissionError(f"Usuário recusado: {resp}")

                code, resp = server.docmd(pass_b64)
                if code != 235: raise PermissionError(f"Senha recusada: {resp}")

                server.send_message(self.msg)

            log.info(f"Relatório enviado por e-mail com sucesso para: {', '.join(self.para)}")
            return True

        except Exception as e:
            log.error(f"Falha crítica no envio do e-mail: {e}")
            return False

    @staticmethod
    def send_report(error: Optional[Exception] = None) -> None:
        """Monta o log da sessão e dispara o relatório para a equipe de TI."""
        sucesso = error is None
        status_icon = "✅" if sucesso else "❌"
        status_texto = "SUCESSO" if sucesso else "FALHA CRÍTICA"
        data_hora = dt.now().strftime('%d/%m/%Y %H:%M:%S')

        secao_erro = ""
        if error is not None:
            traceback_texto = "".join(traceback.format_exception(None, error, error.__traceback__))
            secao_erro = f"\nDETALHES DA EXCEÇÃO:\n------------------------------------------\n{traceback_texto}------------------------------------------\n"

        corpo = (
            f"{status_icon} RELATÓRIO OPERACIONAL — AUTOMAÇÃO AD\n"
            f"==========================================\n"
            f"Data/Hora : {data_hora}\n"
            f"Status    : {status_texto}\n"
            f"==========================================\n"
            f"{secao_erro}"
            f"\nREGISTROS DA SESSÃO E LOGS DETALHADOS:\n"
            f"------------------------------------------\n"
            f"{Log().get_session_log()}\n"
            f"------------------------------------------\n"
        )

        destinatarios_str = os.getenv("EMAIL_RECIPIENTS_ERROR", "")
        destinatarios = destinatarios_str.split(";") if destinatarios_str else [os.getenv("SMTP_USER")]

        Email(
            para=destinatarios,
            titulo=f"{status_icon} Automação AD — Relatório {dt.now().strftime('%d/%m/%Y')} [{status_texto}]",
            corpo_texto=corpo,
        ).enviar()


class DBConnection:
    """Singleton que gerencia conexão de leitura Oracle ERP e banco em memória SQLite."""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(DBConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.DSN = os.getenv("DB_DSN")
            self.USER = os.getenv("DB_USER")
            self.PASSWORD = os.getenv("DB_PASSWORD")

            # Cria o banco SQLite que vai transportar os dados entre a rotina do AD e do S4
            self.sqlite_conn = sqlite3.connect(':memory:', check_same_thread=False)
            self._init_memory_db()

            self._initialized = True

    def _init_memory_db(self):
        cursor = self.sqlite_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dados_automacao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE
            )
        ''')
        self.sqlite_conn.commit()

    def get_inactive_users(self) -> list:
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
                return [[row[0].split('@')[0].strip(), row[1]] for row in cursor.execute(sql)]

    def get_active_users(self) -> list:
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
                return [row[0].split('@')[0].strip() for row in cursor.execute(sql)]

    def insert_db_memory(self, usuarios: list) -> None:
        cursor = self.sqlite_conn.cursor()
        dados_formatados = [(u,) for u in usuarios]
        # INSERT OR IGNORE previne falhas caso um mesmo usuário venha duplicado do AD
        cursor.executemany("INSERT OR IGNORE INTO dados_automacao (usuario) VALUES (?)", dados_formatados)
        self.sqlite_conn.commit()
        log.info(f"SQLite (Memória): {len(usuarios)} registros sincronizados na fila de exclusão web.")

    def select_db_memory(self) -> list:
        cursor = self.sqlite_conn.cursor()
        users = cursor.execute("SELECT usuario FROM dados_automacao").fetchall()
        return [u[0] for u in users]

    def close_memory_db(self):
        self.sqlite_conn.close()


class ManagerAD:
    """Comunica-se com o Active Directory via LDAP para busca e exclusão de privilégios de grupo."""

    def __init__(self):
        self.LDAP_SERVER = os.getenv("LDAP_SERVER")
        self.LDAP_USER = os.getenv("LDAP_USER")
        self.LDAP_PASSWORD = os.getenv("LDAP_PASSWORD")
        self.GRUPO_DN = "CN=EMAIL_S4,OU=Usuarios,DC=grupomonaco,DC=local"
        self.BASE_DN = "DC=grupomonaco,DC=local"
        self.server = Server(self.LDAP_SERVER, get_info=ALL)
        self.db = DBConnection()

    def get_inactive_users(self) -> list:
        try:
            with Connection(self.server, user=self.LDAP_USER, password=self.LDAP_PASSWORD, auto_bind=True) as conn:
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
                return conn.entries
        except Exception as e:
            raise Exception(f"Falha de conexão LDAP com o servidor AD: {e}") from e

    def remove_users(self, usuarios: list) -> None:
        if not usuarios:
            log.info("Sem correspondência: Nenhum usuário validado para remoção do grupo do AD no momento.")
            return

        try:
            with Connection(self.server, user=self.LDAP_USER, password=self.LDAP_PASSWORD, auto_bind=True) as conn:
                log.info(f"Encontrados {len(usuarios)} usuário(s) para remoção.")
                for u in usuarios:
                    user_dn = u.distinguishedName.value
                    sam = u.sAMAccountName.value
                    log.info(f"Removendo: {sam}")

                    # # Edita o atributo member para remover o usuário específico
                    # conn.modify(self.GRUPO_DN, {'member': [(MODIFY_DELETE, [user_dn])]})
                    #
                    # if conn.result['description'] == 'success':
                    #     log.info(f"Usuário {sam} removido com sucesso do grupo de e-mail no AD.")
                    # else:
                    #     raise Exception(f"Falha de privilégios AD ao remover {sam}: {conn.result['description']}")

                # Salva a lista de removidos para a próxima etapa agir na Web
                self.db.insert_db_memory([u.sAMAccountName.value for u in usuarios])

        except Exception as e:
            raise Exception(f"Erro ao aplicar modificações de grupo no LDAP: {e}") from e