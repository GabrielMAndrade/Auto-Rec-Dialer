import os
import re
import time

from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from src.service.driver_service import criar_driver
from src.utils.helpers import log, tirar_print_debug


LOGIN_URL = "https://credtuasset.3c.plus/login"


class CredtuAutomationError(Exception):
    """
    Erro estruturado da automação.

    status:
        código curto usado pelo n8n.

    stage:
        etapa exata em que ocorreu a falha.

    error_type:
        tipo original da exceção do Python/Selenium.

    message:
        mensagem original do erro.
    """

    def __init__(
        self,
        status: str,
        stage: str,
        original_error: Exception,
    ):
        self.status = status
        self.stage = stage
        self.error_type = type(original_error).__name__
        self.message = (
            str(original_error).strip()
            or self.error_type
        )

        super().__init__(
            f"[{status}] {stage}: "
            f"{self.error_type}: {self.message}"
        )

    def to_dict(self):
        return {
            "ok": False,
            "status": self.status,
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,
        }


def executar_etapa(
    status: str,
    stage: str,
    funcao,
    *args,
    **kwargs,
):
    """
    Executa uma etapa e transforma qualquer exceção
    em CredtuAutomationError com status e etapa claros.
    """
    log(
        f"[ETAPA] INÍCIO | "
        f"stage={stage} | status_fallback={status}"
    )

    try:
        resultado = funcao(
            *args,
            **kwargs,
        )

        log(
            f"[ETAPA] OK | "
            f"stage={stage}"
        )

        return resultado

    except CredtuAutomationError as erro:
        log(
            f"[ETAPA] ERRO DETALHADO | "
            f"stage={erro.stage} | "
            f"status={erro.status} | "
            f"error_type={erro.error_type} | "
            f"message={erro.message}"
        )
        raise

    except Exception as erro:
        log(
            f"[ETAPA] ERRO GENÉRICO | "
            f"stage={stage} | "
            f"status={status} | "
            f"error_type={type(erro).__name__} | "
            f"message={str(erro).strip() or type(erro).__name__}"
        )

        raise CredtuAutomationError(
            status=status,
            stage=stage,
            original_error=erro,
        ) from erro


# =========================================================
# XPATHS - LOGIN
# =========================================================

XPATH_EMAIL = (
    "/html/body/div[1]/div[2]/div/div[1]/div/div[1]/"
    "div/div/form/div[1]/input"
)

XPATH_SENHA = (
    "/html/body/div[1]/div[2]/div/div[1]/div/div[1]/"
    "div/div/form/div[2]/div[1]/input"
)

XPATH_BOTAO_ENTRAR = (
    "/html/body/div[1]/div[2]/div/div[1]/div/div[1]/"
    "div/div/form/button"
)


# =========================================================
# XPATHS - CAMPANHA / URA
# =========================================================

XPATH_ABA_URA = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[2]/"
    "div/div/div[1]/ul/li[2]/button"
)

XPATH_ABRIR_TODAS_LISTAS_URA = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[2]/"
    "div/div/div[2]/button"
)

XPATH_TBODY_LISTAS = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[2]/"
    "div/div/div[2]/table/tbody"
)


# =========================================================
# XPATHS - RECICLAGEM
# =========================================================

XPATH_NOME_LISTA_ATUAL = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[1]/h3/span"
)

XPATH_CHECKBOX_1 = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[1]/div[1]/div/div[2]/div/div/div[1]/input"
)

XPATH_CHECKBOX_4 = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[1]/div[1]/div/div[2]/div/div/div[4]/input"
)

XPATH_CHECKBOX_5 = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[1]/div[1]/div/div[2]/div/div/div[5]/input"
)

XPATH_CHECKBOX_6 = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[1]/div[1]/div/div[2]/div/div/div[6]/input"
)

CHECKBOXES_RECICLAGEM = [
    ("checkbox 1", XPATH_CHECKBOX_1),
    ("checkbox 4", XPATH_CHECKBOX_4),
    ("checkbox 5", XPATH_CHECKBOX_5),
    ("checkbox 6", XPATH_CHECKBOX_6),
]

XPATH_CAMPO_NOVO_NOME = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[2]/input"
)

# Janela inesperada que pode aparecer após o primeiro clique em Reciclar.
XPATH_FECHAR_JANELA_EXCLUSAO = (
    "/html/body/div[2]/div[2]/div[3]/button[1]"
)

# Botão final que confirma a reciclagem.
XPATH_BOTAO_FINAL_RECICLAR = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[4]/div[1]/button"
)


def _timeout():
    return int(os.getenv("SELENIUM_TIMEOUT", "30"))


def _sleep_final():
    return float(os.getenv("RECYCLE_SLEEP_SECONDS", "5"))


def esperar_elemento(driver, xpath, timeout=None, exigir_visivel=True):
    timeout = timeout or _timeout()

    def localizar(d):
        try:
            elementos = d.find_elements(By.XPATH, xpath)

            for elemento in elementos:
                try:
                    if not exigir_visivel or elemento.is_displayed():
                        return elemento
                except StaleElementReferenceException:
                    continue

        except Exception:
            pass

        return False

    return WebDriverWait(
        driver,
        timeout,
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    ).until(localizar)


def esperar_clicavel(driver, xpath, timeout=None):
    timeout = timeout or _timeout()

    def localizar(d):
        try:
            elementos = d.find_elements(By.XPATH, xpath)

            for elemento in elementos:
                try:
                    if elemento.is_displayed() and elemento.is_enabled():
                        return elemento
                except StaleElementReferenceException:
                    continue

        except Exception:
            pass

        return False

    return WebDriverWait(
        driver,
        timeout,
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    ).until(localizar)


def clicar(driver, elemento):
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
            elemento,
        )
    except Exception:
        pass

    try:
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elemento)


def texto_elemento(elemento):
    return str(
        elemento.text
        or elemento.get_attribute("textContent")
        or elemento.get_attribute("innerText")
        or ""
    ).strip()


def fazer_login(driver):
    email = str(os.getenv("CREDTU_EMAIL", "")).strip()
    senha = str(os.getenv("CREDTU_PASSWORD", "")).strip()

    if not email or not senha:
        raise CredtuAutomationError(
            status="login_credentials_error",
            stage="validate_login_credentials",
            original_error=RuntimeError(
                "CREDTU_EMAIL e CREDTU_PASSWORD precisam estar preenchidos no .env."
            ),
        )

    log("[AÇÃO LOGIN] Abrindo tela de login...")

    try:
        driver.get(LOGIN_URL)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_navigation_error",
            stage="navigate_login_page",
            original_error=erro,
        ) from erro

    log("[AÇÃO LOGIN] URL de login solicitada. Aguardando document.readyState=complete...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_page_load_error",
            stage="wait_login_page_load",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Página de login terminou o carregamento inicial.")
    log("[AÇÃO LOGIN] Procurando campo de e-mail...")

    try:
        campo_email = esperar_clicavel(
            driver,
            XPATH_EMAIL,
            timeout=20,
        )
    except TimeoutException as erro:
        if "/login" in str(driver.current_url).lower():
            raise CredtuAutomationError(
                status="login_email_field_not_found",
                stage="locate_login_email_field",
                original_error=RuntimeError(
                    "A página de login abriu, mas o campo de e-mail não ficou disponível."
                ),
            ) from erro

        log(
            "[AVISO LOGIN] Campo de e-mail não apareceu, "
            "mas a URL não é mais /login. Considerando sessão já autenticada."
        )
        return
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_email_field_error",
            stage="locate_login_email_field",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Campo de e-mail encontrado.")
    log("[AÇÃO LOGIN] Preenchendo e-mail...")

    try:
        campo_email.clear()
        campo_email.send_keys(email)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_email_fill_error",
            stage="fill_login_email",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] E-mail preenchido.")
    log("[AÇÃO LOGIN] Procurando campo de senha...")

    try:
        campo_senha = esperar_clicavel(
            driver,
            XPATH_SENHA,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_password_field_error",
            stage="locate_login_password_field",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Campo de senha encontrado.")
    log("[AÇÃO LOGIN] Preenchendo senha...")

    try:
        campo_senha.clear()
        campo_senha.send_keys(senha)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_password_fill_error",
            stage="fill_login_password",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Senha preenchida.")
    log("[AÇÃO LOGIN] Procurando botão Entrar...")

    try:
        botao_entrar = esperar_clicavel(
            driver,
            XPATH_BOTAO_ENTRAR,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_button_not_clickable",
            stage="locate_login_button",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Botão Entrar encontrado.")
    log("[AÇÃO LOGIN] Clicando no botão Entrar...")

    try:
        clicar(driver, botao_entrar)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_button_click_error",
            stage="click_login_button",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Clique no botão Entrar executado.")
    log("[AÇÃO LOGIN] Aguardando sair da URL /login...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: "/login" not in str(d.current_url).lower()
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_redirect_error",
            stage="wait_login_redirect",
            original_error=erro,
        ) from erro

    log(
        f"[OK LOGIN] Redirecionamento realizado. "
        f"URL atual: {driver.current_url}"
    )
    log("[AÇÃO LOGIN] Aguardando carregamento completo após autenticação...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_post_load_error",
            stage="wait_login_post_load",
            original_error=erro,
        ) from erro

    time.sleep(2)
    log("[OK LOGIN] Login concluído.")

def abrir_campanha(driver, campaign_id: str):
    url = f"https://credtuasset.3c.plus/manager/campaign/{campaign_id}"

    log(f"[AÇÃO CAMPANHA] Abrindo campanha {campaign_id}...")
    log(f"[DEBUG CAMPANHA] URL esperada: {url}")

    try:
        driver.get(url)
    except Exception as erro:
        raise CredtuAutomationError(
            status="campaign_navigation_error",
            stage="navigate_campaign",
            original_error=erro,
        ) from erro

    log("[AÇÃO CAMPANHA] Navegação solicitada. Aguardando document.readyState=complete...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="campaign_page_load_error",
            stage="wait_campaign_page_load",
            original_error=erro,
        ) from erro

    log("[OK CAMPANHA] Carregamento inicial concluído.")

    # Mantém a mesma espera já existente para estabilização/redirecionamento.
    time.sleep(2)

    try:
        url_atual = str(driver.current_url)
    except Exception as erro:
        raise CredtuAutomationError(
            status="campaign_current_url_error",
            stage="read_campaign_current_url",
            original_error=erro,
        ) from erro

    log(f"[DEBUG CAMPANHA] URL atual após carregamento: {url_atual}")

    if "/login" in url_atual.lower():
        raise CredtuAutomationError(
            status="campaign_session_expired",
            stage="validate_campaign_session",
            original_error=RuntimeError(
                "A sessão da Credtu não permaneceu autenticada ao abrir a campanha."
            ),
        )

    if f"/manager/campaign/{campaign_id}" not in url_atual:
        raise CredtuAutomationError(
            status="campaign_wrong_url",
            stage="validate_campaign_url",
            original_error=RuntimeError(
                f"A campanha não abriu na URL esperada. URL atual: {url_atual}"
            ),
        )

    log("[OK CAMPANHA] Campanha correta validada.")
    log("[AÇÃO CAMPANHA] Aguardando renderização da interface...")

    # Mantém exatamente a espera existente.
    time.sleep(5)

    log("[OK CAMPANHA] Tempo de renderização concluído.")

def _localizar_aba_ura(driver):
    """
    Localiza a aba URA usando o XPath conhecido e seletores de fallback.
    O XPath principal continua sendo o mesmo validado localmente.
    """
    xpaths = [
        XPATH_ABA_URA,
        (
            "//button[normalize-space(translate(., "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))='URA']"
        ),
        (
            "//*[@role='tab' and "
            "normalize-space(translate(., "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))='URA']"
        ),
        (
            "//button[contains(" 
            "normalize-space(translate(., "
            "'abcdefghijklmnopqrstuvwxyz', "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ')), 'URA')]"
        ),
    ]

    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue

        for elemento in elementos:
            try:
                if elemento.is_displayed() and elemento.is_enabled():
                    return elemento
            except StaleElementReferenceException:
                continue

    return False


def _estado_pagina(driver):
    try:
        url = str(driver.current_url)
    except Exception:
        url = "indisponível"

    try:
        titulo = str(driver.title)
    except Exception:
        titulo = "indisponível"

    try:
        ready_state = str(
            driver.execute_script("return document.readyState")
        )
    except Exception:
        ready_state = "indisponível"

    return url, titulo, ready_state


def abrir_ura(driver):
    log("[AÇÃO URA] Aguardando aba URA ficar disponível...")

    try:
        driver.switch_to.default_content()
        log("[DEBUG URA] Contexto do driver ajustado para default_content.")
    except Exception as erro:
        log(
            f"[AVISO URA] Não foi possível executar switch_to.default_content: "
            f"{type(erro).__name__}: {erro}"
        )

    def localizar(d):
        try:
            return _localizar_aba_ura(d)
        except StaleElementReferenceException:
            return False
        except Exception:
            return False

    try:
        botao_ura = WebDriverWait(
            driver,
            45,
            poll_frequency=0.25,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(localizar)

        log("[OK URA] Aba URA encontrada na primeira tentativa.")

    except TimeoutException:
        url, titulo, ready_state = _estado_pagina(driver)

        log(
            "[AVISO URA] Aba URA não apareceu na primeira tentativa. "
            f"URL={url} | título={titulo!r} | readyState={ready_state}."
        )
        log("[AÇÃO URA] Atualizando a campanha uma vez...")

        try:
            driver.refresh()
        except Exception as erro:
            raise CredtuAutomationError(
                status="ura_refresh_error",
                stage="refresh_campaign_for_ura",
                original_error=erro,
            ) from erro

        log("[AÇÃO URA] Refresh executado. Aguardando página carregar...")

        try:
            WebDriverWait(
                driver,
                _timeout(),
                poll_frequency=0.2,
            ).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception as erro:
            raise CredtuAutomationError(
                status="ura_refresh_load_error",
                stage="wait_ura_refresh_load",
                original_error=erro,
            ) from erro

        log("[OK URA] Página carregada após refresh.")

        time.sleep(5)

        try:
            driver.switch_to.default_content()
        except Exception as erro:
            log(
                f"[AVISO URA] switch_to.default_content após refresh falhou: "
                f"{type(erro).__name__}: {erro}"
            )

        log("[AÇÃO URA] Procurando aba URA novamente após refresh...")

        try:
            botao_ura = WebDriverWait(
                driver,
                30,
                poll_frequency=0.25,
                ignored_exceptions=(StaleElementReferenceException,),
            ).until(localizar)

        except TimeoutException as erro:
            url, titulo, ready_state = _estado_pagina(driver)

            try:
                quantidade_xpath = len(
                    driver.find_elements(By.XPATH, XPATH_ABA_URA)
                )
            except Exception:
                quantidade_xpath = -1

            raise CredtuAutomationError(
                status="ura_tab_not_found_after_refresh",
                stage="locate_ura_after_refresh",
                original_error=RuntimeError(
                    "A aba URA não foi encontrada na VPS mesmo após refresh. "
                    f"URL={url}; título={titulo!r}; "
                    f"readyState={ready_state}; "
                    f"elementos_xpath_principal={quantidade_xpath}."
                ),
            ) from erro
        except Exception as erro:
            raise CredtuAutomationError(
                status="ura_tab_locate_error",
                stage="locate_ura_after_refresh",
                original_error=erro,
            ) from erro

        log("[OK URA] Aba URA encontrada após refresh.")

    log("[AÇÃO URA] Clicando na aba URA...")

    try:
        clicar(driver, botao_ura)
    except Exception as erro:
        raise CredtuAutomationError(
            status="ura_tab_click_error",
            stage="click_ura_tab",
            original_error=erro,
        ) from erro

    log("[OK URA] Clique na aba URA executado.")
    log("[AÇÃO URA] Aguardando conteúdo da aba URA aparecer...")

    try:
        WebDriverWait(
            driver,
            30,
            poll_frequency=0.25,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: bool(
                d.find_elements(By.XPATH, XPATH_ABRIR_TODAS_LISTAS_URA)
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="ura_content_load_error",
            stage="wait_ura_content",
            original_error=erro,
        ) from erro

    log("[OK URA] Aba URA aberta e conteúdo identificado.")


def abrir_todas_listas(driver):
    log("[AÇÃO LISTAS] Procurando botão para mostrar todas as listas de URA...")

    try:
        botao_listas = esperar_clicavel(
            driver,
            XPATH_ABRIR_TODAS_LISTAS_URA,
            timeout=45,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="lists_button_not_found",
            stage="locate_open_all_lists_button",
            original_error=erro,
        ) from erro

    log("[OK LISTAS] Botão de listas encontrado.")
    log("[AÇÃO LISTAS] Clicando para abrir todas as listas...")

    try:
        clicar(
            driver,
            botao_listas,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="lists_button_click_error",
            stage="click_open_all_lists_button",
            original_error=erro,
        ) from erro

    log("[OK LISTAS] Clique para abrir listas executado.")
    log("[AÇÃO LISTAS] Aguardando tabela de listas renderizar...")

    try:
        esperar_elemento(
            driver,
            XPATH_TBODY_LISTAS,
            timeout=45,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="lists_table_load_error",
            stage="wait_lists_table",
            original_error=erro,
        ) from erro

    log("[OK LISTAS] Todas as listas de URA carregadas.")

def obter_linhas_visiveis(driver):
    tbody = esperar_elemento(driver, XPATH_TBODY_LISTAS)
    linhas = []

    for linha in tbody.find_elements(By.XPATH, "./tr"):
        try:
            if linha.is_displayed():
                linhas.append(linha)
        except StaleElementReferenceException:
            continue

    return linhas


def esperar_listas(driver):
    log("[AÇÃO LISTAS] Aguardando pelo menos uma linha visível na tabela...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: len(obter_linhas_visiveis(d)) > 0
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="list_rows_load_error",
            stage="wait_visible_list_rows",
            original_error=erro,
        ) from erro

    log("[OK LISTAS] Pelo menos uma linha visível foi encontrada.")


def clicar_opcoes_da_ultima_lista(driver):
    esperar_listas(driver)

    log("[AÇÃO LISTA ATUAL] Lendo linhas visíveis da tabela...")

    try:
        linhas = obter_linhas_visiveis(driver)
    except Exception as erro:
        raise CredtuAutomationError(
            status="latest_list_read_error",
            stage="read_visible_list_rows",
            original_error=erro,
        ) from erro

    if not linhas:
        raise CredtuAutomationError(
            status="latest_list_not_found",
            stage="select_latest_list_row",
            original_error=RuntimeError(
                "Nenhuma lista de URA foi encontrada."
            ),
        )

    ultima_linha = linhas[-1]

    log(
        f"[OK LISTA ATUAL] {len(linhas)} listas visíveis. "
        "Selecionando a última, que é a mais atual."
    )

    try:
        texto = " | ".join(
            parte.strip()
            for parte in ultima_linha.text.splitlines()
            if parte.strip()
        )
        log(f"[DEBUG LISTA ATUAL] Última lista: {texto[:300]}")
    except Exception as erro:
        log(
            f"[AVISO LISTA ATUAL] Não foi possível ler o texto da última linha: "
            f"{type(erro).__name__}: {erro}"
        )

    log("[AÇÃO LISTA ATUAL] Procurando a coluna de opções da última lista...")

    try:
        celula_opcoes = ultima_linha.find_element(
            By.XPATH,
            "./td[10]",
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="latest_list_options_cell_error",
            stage="locate_latest_list_options_cell",
            original_error=erro,
        ) from erro

    log("[OK LISTA ATUAL] Coluna de opções encontrada.")

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
            celula_opcoes,
        )
    except Exception as erro:
        log(
            f"[AVISO LISTA ATUAL] Scroll até a coluna de opções falhou: "
            f"{type(erro).__name__}: {erro}"
        )

    log("[AÇÃO LISTA ATUAL] Procurando botão de opções...")

    try:
        botoes = celula_opcoes.find_elements(By.XPATH, ".//button")
        botao_opcoes = botoes[-1] if botoes else celula_opcoes
    except Exception as erro:
        raise CredtuAutomationError(
            status="latest_list_options_button_error",
            stage="locate_latest_list_options_button",
            original_error=erro,
        ) from erro

    if botoes:
        log(
            f"[OK LISTA ATUAL] {len(botoes)} botão(ões) encontrados na coluna. "
            "Usando o último, conforme lógica atual."
        )
    else:
        log(
            "[AVISO LISTA ATUAL] Nenhum <button> encontrado na coluna. "
            "Mantendo fallback atual: clicar na própria célula."
        )

    log("[AÇÃO LISTA ATUAL] Clicando nas opções da última lista...")

    try:
        clicar(driver, botao_opcoes)
    except Exception as erro:
        raise CredtuAutomationError(
            status="latest_list_options_click_error",
            stage="click_latest_list_options",
            original_error=erro,
        ) from erro

    log("[OK LISTA ATUAL] Clique nas opções executado.")

    return ultima_linha


def fechar_janela_exclusao_se_aparecer(driver):
    log("[AÇÃO RECICLAGEM] Verificando se apareceu janela inesperada de exclusão...")

    try:
        botao_fechar = WebDriverWait(
            driver,
            2,
            poll_frequency=0.05,
        ).until(
            lambda d: next(
                (
                    el
                    for el in d.find_elements(
                        By.XPATH,
                        XPATH_FECHAR_JANELA_EXCLUSAO,
                    )
                    if el.is_displayed() and el.is_enabled()
                ),
                False,
            )
        )

    except TimeoutException:
        log("[OK RECICLAGEM] Janela inesperada de exclusão não apareceu.")
        return False
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_detect_error",
            stage="detect_recycle_exclusion_modal",
            original_error=erro,
        ) from erro

    log("[AVISO RECICLAGEM] Janela de exclusão detectada.")
    log("[AÇÃO RECICLAGEM] Fechando janela de exclusão...")

    try:
        clicar(driver, botao_fechar)
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_click_error",
            stage="click_close_recycle_exclusion_modal",
            original_error=erro,
        ) from erro

    log("[OK RECICLAGEM] Clique para fechar janela executado.")
    log("[AÇÃO RECICLAGEM] Aguardando janela desaparecer...")

    try:
        WebDriverWait(
            driver,
            5,
            poll_frequency=0.05,
        ).until(
            lambda d: not any(
                el.is_displayed()
                for el in d.find_elements(
                    By.XPATH,
                    XPATH_FECHAR_JANELA_EXCLUSAO,
                )
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_close_error",
            stage="wait_recycle_exclusion_modal_close",
            original_error=erro,
        ) from erro

    log("[OK RECICLAGEM] Janela de exclusão fechada.")

    return True


def clicar_reciclar(driver, ultima_linha):
    log("[AÇÃO RECICLAGEM] Abrindo reciclagem da última lista...")
    log("[AÇÃO RECICLAGEM] Procurando botão Reciclar pelo XPath principal da linha...")

    botao_reciclar = None
    origem_botao = None

    try:
        botao_reciclar = WebDriverWait(
            driver,
            5,
            poll_frequency=0.1,
        ).until(
            lambda d: ultima_linha.find_element(
                By.XPATH,
                "./td[10]/div/div/div/div[1]/button",
            )
        )
        origem_botao = "xpath_principal"
        log("[OK RECICLAGEM] Botão Reciclar encontrado pelo XPath principal.")

    except Exception as erro_principal:
        log(
            f"[AVISO RECICLAGEM] XPath principal não localizou o botão Reciclar. "
            f"error_type={type(erro_principal).__name__} | erro={erro_principal}"
        )
        log("[AÇÃO RECICLAGEM] Tentando localizar botão Reciclar pelo fallback textual...")

        xpath_fallback = (
            "//button[contains("
            "translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ',"
            "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç'),"
            "'reciclar')]"
        )

        try:
            botao_reciclar = esperar_clicavel(
                driver,
                xpath_fallback,
                timeout=10,
            )
            origem_botao = "fallback_textual"
        except Exception as erro:
            raise CredtuAutomationError(
                status="recycle_button_not_found",
                stage="locate_recycle_button",
                original_error=RuntimeError(
                    "Não foi possível localizar o botão Reciclar nem pelo XPath "
                    "principal da última linha nem pelo fallback textual. "
                    f"Erro principal: {type(erro_principal).__name__}: "
                    f"{str(erro_principal).strip() or type(erro_principal).__name__}. "
                    f"Erro fallback: {type(erro).__name__}: "
                    f"{str(erro).strip() or type(erro).__name__}."
                ),
            ) from erro

        log("[OK RECICLAGEM] Botão Reciclar encontrado pelo fallback textual.")

    log(
        f"[AÇÃO RECICLAGEM] Clicando no botão Reciclar. "
        f"origem={origem_botao}"
    )

    try:
        clicar(
            driver,
            botao_reciclar,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_button_click_error",
            stage="click_recycle_button",
            original_error=erro,
        ) from erro

    log("[OK RECICLAGEM] Clique no botão Reciclar executado.")

    fechar_janela_exclusao_se_aparecer(driver)

    log("[AÇÃO RECICLAGEM] Aguardando a tela de reciclagem abrir...")
    log("[DEBUG RECICLAGEM] Validação: aguardando elemento do nome da lista atual.")

    try:
        esperar_elemento(
            driver,
            XPATH_NOME_LISTA_ATUAL,
            timeout=_timeout(),
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_screen_load_error",
            stage="wait_recycle_screen",
            original_error=erro,
        ) from erro

    log("[OK RECICLAGEM] Tela de reciclagem aberta e validada.")


def gerar_nome_proxima_reciclagem(nome_atual: str) -> str:
    nome = str(nome_atual or "").strip()

    if not nome:
        raise RuntimeError("O nome atual da lista está vazio.")

    # Remove AUTO.R anterior para não duplicar em novas reciclagens.
    nome_base = re.sub(
        r"\s*\|\s*AUTO\.R\s*$",
        "",
        nome,
        flags=re.IGNORECASE,
    ).strip()

    match = re.search(
        r"\bREC\s*(\d+)\b",
        nome_base,
        flags=re.IGNORECASE,
    )

    if not match:
        raise RuntimeError(
            f"Não encontrei o número REC no nome da lista: {nome_atual!r}"
        )

    numero_atual = int(match.group(1))
    proximo_numero = numero_atual + 1

    novo_nome = (
        nome_base[:match.start()]
        + f"REC{proximo_numero}"
        + nome_base[match.end():]
    ).strip()

    return f"{novo_nome} | AUTO.R"


def obter_nome_atual_e_novo(driver):
    log("[AÇÃO NOME] Procurando nome atual da lista na tela de reciclagem...")

    try:
        elemento = esperar_elemento(
            driver,
            XPATH_NOME_LISTA_ATUAL,
            timeout=_timeout(),
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="current_list_name_element_error",
            stage="locate_current_list_name",
            original_error=erro,
        ) from erro

    log("[OK NOME] Elemento do nome atual encontrado.")
    log("[AÇÃO NOME] Lendo texto do nome atual...")

    try:
        nome_atual = texto_elemento(elemento)
    except Exception as erro:
        raise CredtuAutomationError(
            status="current_list_name_read_error",
            stage="read_current_list_name",
            original_error=erro,
        ) from erro

    if not nome_atual:
        raise CredtuAutomationError(
            status="current_list_name_empty",
            stage="validate_current_list_name",
            original_error=RuntimeError(
                "Não consegui ler o nome atual da lista."
            ),
        )

    log(f"[OK NOME] Nome atual lido: {nome_atual}")
    log("[AÇÃO NOME] Gerando próximo nome de reciclagem...")

    try:
        novo_nome = gerar_nome_proxima_reciclagem(
            nome_atual
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="new_list_name_generate_error",
            stage="generate_next_list_name",
            original_error=erro,
        ) from erro

    log(f"[OK NOME] Novo nome gerado: {novo_nome}")

    return nome_atual, novo_nome


def checkbox_esta_marcado(driver, elemento):
    try:
        if elemento.is_selected():
            return True
    except Exception:
        pass

    try:
        return bool(
            driver.execute_script(
                "return arguments[0].checked === true;",
                elemento,
            )
        )
    except Exception:
        return False


def marcar_checkbox(driver, nome, xpath):
    codigo_checkbox = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        str(nome).strip().lower(),
    ).strip("_") or "checkbox"

    log(f"[AÇÃO CHECKBOX] Procurando {nome}...")

    try:
        checkbox = esperar_elemento(
            driver,
            xpath,
            timeout=_timeout(),
            exigir_visivel=False,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status=f"{codigo_checkbox}_not_found",
            stage=f"locate_{codigo_checkbox}",
            original_error=erro,
        ) from erro

    log(f"[OK CHECKBOX] {nome} encontrado.")
    log(f"[AÇÃO CHECKBOX] Verificando estado atual de {nome}...")

    try:
        ja_marcado = checkbox_esta_marcado(
            driver,
            checkbox,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status=f"{codigo_checkbox}_state_error",
            stage=f"read_{codigo_checkbox}_state",
            original_error=erro,
        ) from erro

    if ja_marcado:
        log(f"[OK CHECKBOX] {nome} já estava marcado.")
        return

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
            checkbox,
        )
    except Exception as erro:
        log(
            f"[AVISO CHECKBOX] Scroll até {nome} falhou: "
            f"{type(erro).__name__}: {erro}"
        )

    log(f"[AÇÃO CHECKBOX] Marcando {nome}...")

    try:
        checkbox.click()
    except Exception as erro_click:
        log(
            f"[AVISO CHECKBOX] Clique normal em {nome} falhou. "
            f"Tentando JavaScript. "
            f"error_type={type(erro_click).__name__} | erro={erro_click}"
        )

        try:
            driver.execute_script(
                "arguments[0].click();",
                checkbox,
            )
        except Exception as erro_js:
            raise CredtuAutomationError(
                status=f"{codigo_checkbox}_click_error",
                stage=f"click_{codigo_checkbox}",
                original_error=RuntimeError(
                    f"Falha no clique normal e no clique JavaScript em {nome}. "
                    f"Normal: {type(erro_click).__name__}: "
                    f"{str(erro_click).strip() or type(erro_click).__name__}. "
                    f"JavaScript: {type(erro_js).__name__}: "
                    f"{str(erro_js).strip() or type(erro_js).__name__}."
                ),
            ) from erro_js

    log(f"[AÇÃO CHECKBOX] Confirmando que {nome} ficou marcado...")

    try:
        WebDriverWait(
            driver,
            5,
            poll_frequency=0.05,
        ).until(
            lambda d: checkbox_esta_marcado(
                d,
                checkbox,
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status=f"{codigo_checkbox}_verify_error",
            stage=f"verify_{codigo_checkbox}_checked",
            original_error=erro,
        ) from erro

    log(f"[OK CHECKBOX] {nome} marcado e validado.")


def marcar_boxes_reciclagem(driver):
    log(
        f"[AÇÃO CHECKBOX] Iniciando marcação de "
        f"{len(CHECKBOXES_RECICLAGEM)} opções de reciclagem..."
    )

    for indice, (nome, xpath) in enumerate(
        CHECKBOXES_RECICLAGEM,
        start=1,
    ):
        log(
            f"[AÇÃO CHECKBOX] Processando opção "
            f"{indice}/{len(CHECKBOXES_RECICLAGEM)}: {nome}"
        )
        marcar_checkbox(
            driver,
            nome,
            xpath,
        )

    log("[OK CHECKBOX] Todas as opções de reciclagem foram processadas.")


def preencher_novo_nome(driver, novo_nome):
    log("[AÇÃO NOME] Procurando campo para o novo nome da lista...")

    try:
        campo = esperar_clicavel(
            driver,
            XPATH_CAMPO_NOVO_NOME,
            timeout=_timeout(),
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="list_name_input_not_found",
            stage="locate_new_list_name_input",
            original_error=erro,
        ) from erro

    log("[OK NOME] Campo do novo nome encontrado.")
    log("[AÇÃO NOME] Clicando no campo do novo nome...")

    try:
        campo.click()
    except Exception as erro:
        raise CredtuAutomationError(
            status="list_name_input_click_error",
            stage="click_new_list_name_input",
            original_error=erro,
        ) from erro

    log("[AÇÃO NOME] Limpando valor atual do campo...")

    try:
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.BACKSPACE)
    except Exception as erro:
        raise CredtuAutomationError(
            status="list_name_input_clear_error",
            stage="clear_new_list_name_input",
            original_error=erro,
        ) from erro

    log(f"[AÇÃO NOME] Digitando novo nome: {novo_nome}")

    try:
        campo.send_keys(novo_nome)
    except Exception as erro:
        raise CredtuAutomationError(
            status="list_name_input_type_error",
            stage="type_new_list_name",
            original_error=erro,
        ) from erro

    log("[AÇÃO NOME] Validando se o valor foi preenchido corretamente...")

    try:
        WebDriverWait(
            driver,
            5,
            poll_frequency=0.05,
        ).until(
            lambda d: str(
                campo.get_attribute("value") or ""
            ).strip() == novo_nome
        )
    except Exception as erro:
        try:
            valor_atual = str(
                campo.get_attribute("value") or ""
            ).strip()
        except Exception:
            valor_atual = "<indisponível>"

        raise CredtuAutomationError(
            status="list_name_input_verify_error",
            stage="verify_new_list_name",
            original_error=RuntimeError(
                f"O campo não confirmou o novo nome esperado. "
                f"Esperado={novo_nome!r}; atual={valor_atual!r}."
            ),
        ) from erro

    log(f"[OK NOME] Novo nome preenchido e validado: {novo_nome}")


def finalizar_reciclagem(driver):
    log("[AÇÃO CONFIRMAÇÃO] Procurando botão final de Reciclar...")

    try:
        botao = esperar_clicavel(
            driver,
            XPATH_BOTAO_FINAL_RECICLAR,
            timeout=_timeout(),
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_confirm_button_not_found",
            stage="locate_recycle_confirm_button",
            original_error=erro,
        ) from erro

    log("[OK CONFIRMAÇÃO] Botão final de Reciclar encontrado.")
    log("[AÇÃO CONFIRMAÇÃO] Clicando no botão final de Reciclar...")

    try:
        clicar(
            driver,
            botao,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_confirm_click_error",
            stage="click_recycle_confirm_button",
            original_error=erro,
        ) from erro

    log("[OK CONFIRMAÇÃO] Clique final executado.")

    log(
        f"[AÇÃO CONFIRMAÇÃO] Mantendo espera final de "
        f"{_sleep_final():g}s antes de fechar o Chrome..."
    )

    time.sleep(_sleep_final())

    log("[OK CONFIRMAÇÃO] Espera final concluída.")


def salvar_html_debug(driver, prefixo="erro"):
    """
    Salva o HTML que o Chrome está vendo para diagnóstico na VPS.
    """
    try:
        raiz_projeto = os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )
        pasta = os.path.join(raiz_projeto, "screenshots")
        os.makedirs(pasta, exist_ok=True)

        agora = time.strftime("%Y-%m-%d_%H-%M-%S")
        caminho = os.path.join(
            pasta,
            f"{prefixo}_{agora}.html",
        )

        with open(caminho, "w", encoding="utf-8") as arquivo:
            arquivo.write(driver.page_source)

        log(f"[DEBUG] HTML salvo em: {caminho}")
        return caminho

    except Exception as erro:
        log(f"[AVISO] Não consegui salvar HTML de debug: {erro}")
        return None


def executar_reciclagem(campaign_id: str) -> dict:
    """
    Executa toda a reciclagem e devolve um resultado estruturado.

    Sucesso:
        {
            "ok": True,
            "status": "success",
            "campaign_id": "...",
            "nome_anterior": "...",
            "novo_nome": "..."
        }

    Falha:
        levanta CredtuAutomationError.
        A API transforma em JSON para o n8n.
    """

    campaign_id = str(
        campaign_id or ""
    ).strip()

    if (
        not campaign_id
        or not campaign_id.isdigit()
    ):
        raise CredtuAutomationError(
            status="invalid_campaign_id",
            stage="validation",
            original_error=ValueError(
                "campaign_id deve conter somente números."
            ),
        )

    driver = None
    nome_atual = None
    novo_nome = None

    try:
        log("===================================================")
        log(
            f" CREDTU AUTO RECICLAGEM | "
            f"CAMPANHA {campaign_id}"
        )
        log("===================================================")

        # 1. Chrome
        driver = executar_etapa(
            "chrome_start_error",
            "open_chrome",
            criar_driver,
        )

        # 2. Login
        executar_etapa(
            "login_error",
            "login",
            fazer_login,
            driver,
        )

        # 3. Campanha
        executar_etapa(
            "campaign_open_error",
            "open_campaign",
            abrir_campanha,
            driver,
            campaign_id,
        )

        # 4. Aba URA
        executar_etapa(
            "ura_tab_error",
            "open_ura",
            abrir_ura,
            driver,
        )

        # 5. Abrir todas as listas
        executar_etapa(
            "lists_open_error",
            "open_all_lists",
            abrir_todas_listas,
            driver,
        )

        # 6. Localizar a lista mais atual
        ultima_linha = executar_etapa(
            "latest_list_error",
            "select_latest_list",
            clicar_opcoes_da_ultima_lista,
            driver,
        )

        # 7. Abrir reciclagem
        executar_etapa(
            "recycle_open_error",
            "open_recycle",
            clicar_reciclar,
            driver,
            ultima_linha,
        )

        # 8. Ler e gerar novo nome
        nome_atual, novo_nome = executar_etapa(
            "list_name_error",
            "generate_list_name",
            obter_nome_atual_e_novo,
            driver,
        )

        # 9. Marcar checkboxes
        executar_etapa(
            "checkbox_error",
            "mark_recycle_options",
            marcar_boxes_reciclagem,
            driver,
        )

        # 10. Preencher nome
        executar_etapa(
            "list_name_fill_error",
            "fill_new_list_name",
            preencher_novo_nome,
            driver,
            novo_nome,
        )

        # 11. Confirmar reciclagem
        executar_etapa(
            "recycle_confirm_error",
            "confirm_recycle",
            finalizar_reciclagem,
            driver,
        )

        log(
            "[CREDTU] Reciclagem concluída "
            "com sucesso."
        )

        log(
            f"[CREDTU] {nome_atual} "
            f"-> {novo_nome}"
        )

        return {
            "ok": True,
            "status": "success",
            "campaign_id": campaign_id,
            "nome_anterior": nome_atual,
            "novo_nome": novo_nome,
        }

    except CredtuAutomationError as erro:
        # Screenshot + HTML para investigação. Em ura_tab_error o nome do arquivo
        # deixa claro que a falha ocorreu antes de abrir a aba URA.
        if driver is not None:
            if erro.status == "ura_tab_error":
                prefixo_debug = f"ura_tab_error_{campaign_id}"
            else:
                prefixo_debug = f"erro_campaign_{campaign_id}"

            tirar_print_debug(
                driver,
                prefixo=prefixo_debug,
            )
            salvar_html_debug(
                driver,
                prefixo=prefixo_debug,
            )

        raise

    except Exception as erro:
        # Fallback para algum erro inesperado fora das etapas.
        if driver is not None:
            tirar_print_debug(
                driver,
                prefixo=(
                    f"erro_campaign_"
                    f"{campaign_id}"
                ),
            )

        raise CredtuAutomationError(
            status="unexpected_error",
            stage="unknown",
            original_error=erro,
        ) from erro

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass