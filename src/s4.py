# -*- coding: utf-8 -*-
"""
Automação Web - Portal S4
Módulo responsável pela interação via Selenium para exclusão de caixas de e-mail.
"""

import os
from time import sleep, time
from typing import Tuple, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

from utils import DBConnection, Log

# Instância global de Log para manter rastro das ações
log = Log().get_logger()


class FrameManager:
    """Gerencia a navegação e interações de forma inteligente dentro de iframes do Selenium."""

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.default_timeout = 10  # Tempo limite padrão de 10 segundos

    def _localizar_frame_do_elemento(self, locator_type: By, locator_value: str) -> Tuple[
        bool, Optional[webdriver.remote.webelement.WebElement]]:
        """Varre os frames da página atual em busca de um elemento e foca no frame correto."""
        self.driver.switch_to.default_content()

        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        frames = self.driver.find_elements(By.TAG_NAME, "frame")
        todos_frames = iframes + frames

        for frame in todos_frames:
            try:
                self.driver.switch_to.frame(frame)
                elementos = self.driver.find_elements(locator_type, locator_value)
                if elementos:
                    return True, frame
            except Exception:
                pass
            finally:
                self.driver.switch_to.default_content()

        return False, None

    def click_on_element(self, locator_type: By, locator_value: str, usar_js: bool = True,
                         manter_frame: bool = True) -> bool:
        """Localiza o frame contendo o elemento, foca nele e realiza o clique."""
        encontrou, frame = self._localizar_frame_do_elemento(locator_type, locator_value)

        if encontrou:
            self.driver.switch_to.frame(frame)
            try:
                elem = WebDriverWait(self.driver, self.default_timeout).until(
                    EC.element_to_be_clickable((locator_type, locator_value))
                )
                sleep(2)
                if usar_js:
                    self.driver.execute_script("arguments[0].click();", elem)
                else:
                    elem.click()
                    sleep(2)

                return True
            except TimeoutException:
                log.warning(f"❌ Elemento '{locator_value}' encontrado no frame, mas não está clicável.")
                return False
            finally:
                if not manter_frame:
                    self.driver.switch_to.default_content()
        else:
            log.warning(f"❌ Elemento '{locator_value}' não encontrado em nenhum frame.")
            return False

    def write_on_element(self, locator_type: By, locator_value: str, texto: str, limpar_antes: bool = True,
                         manter_frame: bool = True) -> bool:
        """Localiza o frame do input, foca nele, insere o texto e pressiona ENTER."""
        encontrou, frame = self._localizar_frame_do_elemento(locator_type, locator_value)

        if encontrou:
            self.driver.switch_to.frame(frame)
            try:
                input_elem = WebDriverWait(self.driver, self.default_timeout).until(
                    EC.visibility_of_element_located((locator_type, locator_value))
                )
                sleep(2)
                if limpar_antes:
                    input_elem.clear()

                input_elem.send_keys(texto)
                sleep(0.2)
                input_elem.send_keys(Keys.ENTER)

                return True
            except TimeoutException:
                log.warning(f"❌ Campo de entrada '{locator_value}' indisponível para escrita.")
                return False
            finally:
                if not manter_frame:
                    self.driver.switch_to.default_content()
        else:
            log.warning(f"❌ Campo de entrada '{locator_value}' não encontrado.")
            return False

    def get_text_on_element(self, locator_type: By, locator_value: str, manter_no_frame: bool = True) -> str:
        """Localiza o elemento e retorna seu conteúdo de texto ou valor."""
        encontrou, frame = self._localizar_frame_do_elemento(locator_type, locator_value)

        if encontrou:
            self.driver.switch_to.frame(frame)
            try:
                elem = WebDriverWait(self.driver, self.default_timeout).until(
                    EC.visibility_of_element_located((locator_type, locator_value))
                )
                texto = elem.text

                if not texto:
                    texto = elem.get_attribute("value") or elem.get_attribute("title") or ""

                return texto.strip()
            except TimeoutException:
                log.warning(f"❌ Tempo limite excedido para leitura no elemento '{locator_value}'.")
                return ""
            finally:
                if not manter_no_frame:
                    self.driver.switch_to.default_content()
        return ""

    def wait_loading_disappear(self, xpath_loading: str = "/html/body/div[8]/div[2]", tempo_limite: int = 1800) -> bool:
        """Aguarda a tela/overlay de carregamento desaparecer."""
        self.driver.switch_to.default_content()
        log.info("⏳ Aguardando processamento da requisição no servidor S4...")
        inicio = time()

        try:
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, xpath_loading))
            )
        except TimeoutException:
            pass

        try:
            WebDriverWait(self.driver, tempo_limite).until(
                EC.invisibility_of_element_located((By.XPATH, xpath_loading))
            )
            duracao = round(time() - inicio, 5)
            log.info(f"✨ Loading concluído após {duracao}s. Prosseguindo...")
            sleep(10)
            return True
        except TimeoutException:
            log.error(f"⚠️ O loading da página travou e não sumiu após {tempo_limite} segundos.")
            return False

    def voltar_para_raiz(self):
        self.driver.switch_to.default_content()


class S4EmailAutomation:
    """Classe controladora do fluxo de negócio web no S4."""

    def __init__(self):
        self.db = DBConnection()
        self.driver = self._inicializar_driver()
        self.fm = FrameManager(self.driver)

    def _inicializar_driver(self) -> webdriver.Chrome:
        options = Options()
        options.accept_insecure_certs = True
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--start-maximized')
        return webdriver.Chrome(options=options)

    def realizar_login(self) -> bool:
        url = os.getenv('S4_URL')
        if not url:
            raise ValueError("A variável 'S4_URL' não está configurada no .env")

        log.info(f"Conectando ao sistema S4")
        self.driver.get(url)
        sleep(1)

        log.info('Inserindo credenciais de acesso...')
        elem_user = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'logins4'))
        )
        elem_user.send_keys(os.getenv('S4_USER', '') + Keys.TAB)
        sleep(1)

        elem_pass = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'senhas4'))
        )
        elem_pass.send_keys(os.getenv('S4_PASS', '') + Keys.ENTER)
        sleep(1)
        self._tratar_modal_inicial()
        sleep(1)
        return True

    def _tratar_modal_inicial(self):
        try:
            modal = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.CLASS_NAME, "modal-footer"))
            )
            log.info("Caixa de atualização de sistema detectada. Fechando modal...")
            sleep(1)
            modal.find_element(By.TAG_NAME, "button").click()
            sleep(1)
        except TimeoutException:
            pass

    def acessar_menu_usuarios(self):
        log.info("Acessando o menu principal de usuários de e-mail...")
        btn_menu = WebDriverWait(self.driver, 30).until(
            EC.element_to_be_clickable(
                (By.XPATH, '/html/body/table/tbody/tr/td/table/tbody/tr[1]/td/table/tbody/tr[1]/td[1]/a/img'))
        )
        btn_menu.click()
        self.fm.click_on_element(By.ID, "email_usuarios", manter_frame=False)

    def processar_exclusoes(self):
        usuarios_inativos = self.db.select_db_memory()
        log.info(f"Total de {len(usuarios_inativos)} usuários pendentes de exclusão na fila de memória.")

        for usuario in usuarios_inativos:
            log.info(f"Iniciando busca no painel web para a conta: '{usuario}'")
            usuario_completo = f'{usuario}@grupomonaco.com.br'
            self.fm.write_on_element(By.ID, "gs_mail", usuario_completo)
            sleep(2)

            # Validação Dupla de Identidade
            # seletor_xpath = f"//td[@title='{usuario_completo}'"
            user_s4_completo = self.fm.get_text_on_element(
                By.XPATH, '/html/body/div[6]/div[3]/div[4]/div/table/tbody/tr[2]/td[3]'
            )
            if not user_s4_completo:
                log.warning(f"Usuário '{usuario_completo}' não listado na tabela (já excluído ou não existe). Pulando.")
                continue

            if user_s4_completo != usuario_completo:
                log.error(
                    f"Divergência de Identidade! Retornado: '{user_s4_completo}' | Esperado: '{usuario_completo}'. Exclusão ABORTADA para este registro.")
                continue

            log.info(f"Identidade validada com sucesso. Removendo permanentemente a conta: {user_s4_completo}")

            # Botão da Lixeira
            self.fm.click_on_element(By.XPATH, '/html/body/div[6]/div[3]/div[4]/div/table/tbody/tr[2]/td[29]/img')
            sleep(2)
            # Confirmar Pop-up de exclusão
            self.fm.click_on_element(By.XPATH, '/html/body/div[8]/div[3]/div/button[1]')

            # Aguarda a tela de carregamento para garantir sincronia
            self.fm.wait_loading_disappear()

    def fechar_s4(self):
        log.info("Fechando s4...")
        self.fm.voltar_para_raiz()
        sleep(2)
        element = self.driver.find_element(By.XPATH, '/html/body/table/tbody/tr/td/table/tbody/tr[1]/td/table/tbody/tr[1]/td[16]/a/img')
        element.click()
        sleep(5)

    def fechar_driver(self):
        if self.driver:
            self.driver.quit()
            log.info("Navegador fechado e sessões de memória de vídeo limpas.")