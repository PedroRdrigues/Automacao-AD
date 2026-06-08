# -*- coding: utf-8 -*-
"""
Created on Fri Oct  4 17:13:35 2024

@author: PedroRdrigues
Refactored for performance, stability, and clean code principles.
"""

import os
from time import sleep, time
from typing import List, Tuple, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

from dotenv import load_dotenv
from utils import DBConnection

# Carrega as variáveis de ambiente
load_dotenv(verbose=True)


class FrameManager:
    """Classe responsável por gerenciar a navegação e interações dentro de iframes do Selenium."""

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.default_timeout = 10  # Tempo limite padrão mais realista (10 segundos)

    def _localizar_frame_do_elemento(self, locator_type: By, locator_value: str) -> Tuple[
        bool, Optional[webdriver.remote.webelement.WebElement]]:
        """
        Varre todos os frames da página atual em busca de um elemento específico.
        Retorna (True, frame_elemento) se encontrado, ou (False, None).
        """
        self.driver.switch_to.default_content()

        # Obtém todos os frames e iframes da raiz
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        frames = self.driver.find_elements(By.TAG_NAME, "frame")
        todos_frames = iframes + frames

        for frame in todos_frames:
            try:
                self.driver.switch_to.frame(frame)
                # Procura imediata sem espera explícita para evitar lentidão na varredura
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
                if usar_js:
                    self.driver.execute_script("arguments[0].click();", elem)
                else:
                    elem.click()
                print(f"✅ Clique realizado em '{locator_value}' no frame.")
                return True
            except TimeoutException:
                print(f"❌ Elemento '{locator_value}' encontrado no frame, mas não ficou clicável.")
                if not manter_frame:
                    self.driver.switch_to.default_content()
                return False
            finally:
                if not manter_frame:
                    self.driver.switch_to.default_content()
        else:
            print(f"❌ Elemento '{locator_value}' não foi encontrado em nenhum frame.")
            return False

    def write_on_element(self, locator_type: By, locator_value: str, texto: str, limpar_antes: bool = True,
                         manter_frame: bool = True) -> bool:
        """Localiza o frame contendo o input, foca nele, insere o texto e pressiona ENTER."""
        encontrou, frame = self._localizar_frame_do_elemento(locator_type, locator_value)

        if encontrou:
            self.driver.switch_to.frame(frame)
            try:
                input_elem = WebDriverWait(self.driver, self.default_timeout).until(
                    EC.visibility_of_element_located((locator_type, locator_value))
                )
                if limpar_antes:
                    input_elem.clear()

                input_elem.send_keys(texto)
                sleep(0.5)  # Pequeno delay para garantir o preenchimento seguro antes do enter
                input_elem.send_keys(Keys.ENTER)
                return True
            except TimeoutException:
                print(
                    f"❌ Campo de entrada '{locator_value}' encontrado no frame, mas não está disponível para escrita.")
                if not manter_frame:
                    self.driver.switch_to.default_content()
                return False
            finally:
                if not manter_frame:
                    self.driver.switch_to.default_content()
        else:
            print(f"❌ Campo de entrada '{locator_value}' não encontrado em nenhum frame.")
            return False

    def get_text_on_element(self, locator_type: By, locator_value: str, manter_no_frame: bool = True) -> str:
        """Localiza o frame contendo o elemento e retorna seu conteúdo de texto ou atributo principal."""
        encontrou, frame = self._localizar_frame_do_elemento(locator_type, locator_value)

        if encontrou:
            self.driver.switch_to.frame(frame)
            try:
                elem = WebDriverWait(self.driver, self.default_timeout).until(
                    EC.visibility_of_element_located((locator_type, locator_value))
                )
                texto = elem.text

                # Fallback caso o texto interno venha vazio
                if not texto:
                    texto = elem.get_attribute("value") or elem.get_attribute("title") or ""

                return texto.strip()
            except TimeoutException:
                print(f"❌ Elemento '{locator_value}' encontrado no frame, mas expirou o tempo de leitura.")
                return ""
            finally:
                if not manter_no_frame:
                    self.driver.switch_to.default_content()
        return ""

    def wait_loading_disappear(self, xpath_loading: str = "/html/body/div[8]/div[2]", tempo_limite: int = 30) -> bool:
        """Aguarda de forma otimizada até que a janela/overlay de carregamento desapareça da tela."""
        self.driver.switch_to.default_content()
        print("⏳ Aguardando a tela de loading sumir...")
        inicio = time()

        # Aguarda brevemente para ver se o loading de fato aparece na tela
        try:
            WebDriverWait(self.driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, xpath_loading))
            )
            print("🔄 Loading detectado. Aguardando conclusão da tarefa no servidor...")
        except TimeoutException:
            # Caso o processo seja tão rápido que o loading nem apareça
            pass

        # Aguarda o sumiço definitivo do elemento
        try:
            WebDriverWait(self.driver, tempo_limite).until(
                EC.invisibility_of_element_located((By.XPATH, xpath_loading))
            )
            duracao = round(time() - inicio, 2)
            print(f"✨ Concluído! O loading sumiu após {duracao}s. Prosseguindo...")
            sleep(1.5)  # Breve pausa de estabilização do DOM pós-loading
            return True
        except TimeoutException:
            print(f"⚠️ Alerta: O loading persistiu por mais de {tempo_limite} segundos. O sistema pode estar instável.")
            return False

    def voltar_para_raiz(self):
        """Volta o foco do Selenium para fora de qualquer frame."""
        self.driver.switch_to.default_content()


class S4EmailAutomation:
    """Classe controladora responsável por gerenciar as regras de negócio do fluxo de limpeza do S4."""

    def __init__(self):
        self.db = DBConnection()
        self.driver = self._inicializar_driver()
        self.fm = FrameManager(self.driver)

    def _inicializar_driver(self) -> webdriver.Chrome:
        """Configura e inicializa o WebDriver do Chrome."""
        options = Options()
        options.accept_insecure_certs = True
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--start-maximized')
        return webdriver.Chrome(options=options)

    def realizar_login(self) -> bool:
        """Realiza o processo de login na intranet S4."""
        url = os.getenv('S4_URL')
        if not url:
            raise ValueError("A variável de ambiente 'S4_URL' não está configurada.")

        print(f"Conectando ao sistema S4 em: {url}")
        self.driver.get(url)
        sleep(1)

        # Preenche as credenciais de acesso
        print('⌨️ Inserindo username...')
        elem_user = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'logins4'))
        )
        elem_user.send_keys(os.getenv('S4_USER', '') + Keys.TAB)

        print('⌨️ Inserindo password...')
        elem_pass = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'senhas4'))
        )
        elem_pass.send_keys(os.getenv('S4_PASS', '') + Keys.ENTER)

        # Validação/Fechamento de Modal de Atualização se houver
        self._tratar_modal_inicial()
        return True

    def _tratar_modal_inicial(self):
        """Identifica se a caixa de diálogo/atualização apareceu e a fecha se necessário."""
        try:
            modal = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.CLASS_NAME, "modal-footer"))
            )
            print("📢 Caixa de atualização detectada! Fechando modal...")
            botao_fechar = modal.find_element(By.TAG_NAME, "button")
            botao_fechar.click()
            sleep(1)
        except TimeoutException:
            print("ℹ️ Nenhuma caixa de atualização pendente identificada. Seguindo...")

    def acessar_menu_usuarios(self):
        """Navega pelo menu principal até a tela de gerenciamento de e-mails."""
        print("📂 Acessando menu principal...")
        btn_menu = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, '/html/body/table/tbody/tr/td/table/tbody/tr[1]/td/table/tbody/tr[1]/td[1]/a/img'))
        )
        btn_menu.click()

        # Clique no submenu de usuários usando o gerenciador de frames
        self.fm.click_on_element(By.ID, "email_usuarios", manter_frame=False)

    def processar_exclusoes(self):
        """Busca os usuários inativos do banco de dados na memória e realiza as exclusões necessárias."""
        usuarios_inativos = self.db.select_db_memory()
        print(f"📋 Total de {len(usuarios_inativos)} usuários inativos para processar.")

        for usuario in usuarios_inativos:
            print(f"\n🔍 Iniciando verificação para o usuário: {usuario}")

            # Escreve o usuário na barra de pesquisa (ID: gs_mail)
            self.fm.write_on_element(By.ID, "gs_mail", usuario)
            sleep(1.5)  # Pausa necessária para atualização da listagem dinâmica pós-busca

            # Obtém o usuário retornado na tabela para certificar-se de que é a conta correta
            user_s4_completo = self.fm.get_text_on_element(
                By.XPATH,
                '/html/body/div[6]/div[3]/div[4]/div/table/tbody/tr[2]/td[3]'
            )

            if not user_s4_completo:
                print(f"⚠️ Usuário '{usuario}' não encontrado na tabela de listagem.")
                continue

            user_s4 = user_s4_completo.split('@')[0].strip()

            if user_s4 != usuario:
                print(
                    f"⚠️ Divergência de dados detectada (Encontrado: '{user_s4}' | Esperado: '{usuario}'). Abortando deleção deste registro.")
                continue

            print(f"🎯 Registro confirmado e validado! Removendo: {user_s4}")

            # Clica no botão de Excluir da linha correspondente (td[29]/img)
            self.fm.click_on_element(By.XPATH, '/html/body/div[6]/div[3]/div[4]/div/table/tbody/tr[2]/td[29]/img')
            sleep(1)

            # Clica no botão de confirmação da janela de exclusão
            self.fm.click_on_element(By.XPATH, '/html/body/div[8]/div[3]/div/button[1]')

            # Aguarda a finalização do processo no servidor
            self.fm.wait_loading_disappear()

    def fechar_driver(self):
        """Garante o encerramento correto do processo do navegador."""
        if self.driver:
            self.driver.quit()
            print("🔌 Navegador fechado e sessões limpas.")


def executar_fluxo_completo():
    """Inicializa e executa o fluxo completo de automação com tratamento de segurança."""
    automacao = S4EmailAutomation()
    try:
        automacao.realizar_login()
        automacao.acessar_menu_usuarios()
        automacao.processar_exclusoes()
    except Exception as e:
        print(f"💥 Ocorreu uma falha grave durante a execução: {e}")
    finally:
        automacao.fechar_driver()


if __name__ == "__main__":
    # Inicialização e sementeira de dados de teste (SQLite em memória compartilhado via Singleton)
    db = DBConnection()
    db.insert_db_memory([
        'teste_automacao3',
        'teste_automacao1',
        'teste_automacao2',
        'teste_automacao4',
        'teste_automacao5'
    ])

    print("📊 Lista de usuários na fila de exclusão:")
    print(db.select_db_memory())

    # Inicia a automação web
    executar_fluxo_completo()

    # Fecha o banco de dados principal
    db.close_memory_db()