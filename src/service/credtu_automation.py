import os
import re
import time
import traceback

import pyotp

from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from src.service.driver_service import criar_driver
from src.utils.helpers import log, tirar_print_debug


DEFAULT_DIALER_BASE_URL = "https://somasoluoes.3c.plus"


def _dialer_base_url():
    return str(
        os.getenv(
            "DIALER_BASE_URL",
            DEFAULT_DIALER_BASE_URL,
        )
    ).strip().rstrip("/")


def _dialer_login_url():
    return f"{_dialer_base_url()}/login"


def _normalizar_codigo_diagnostico(valor):
    texto = re.sub(
        r"(?<!^)(?=[A-Z])",
        "_",
        str(valor or ""),
    )
    texto = re.sub(
        r"[^a-zA-Z0-9]+",
        "_",
        texto,
    )
    return texto.strip("_").lower() or "unknown"


def _descricao_erro(status, stage, error_type, message):
    """
    Traduz os códigos técnicos já existentes para uma descrição
    operacional mais fácil de interpretar no n8n.

    IMPORTANTE:
    esta função não toma decisões nem altera o fluxo da automação.
    """
    mapa = {
        "invalid_campaign_id": (
            "ID de campanha inválido.",
            "O campaign_id recebido está vazio ou contém caracteres não numéricos.",
            False,
        ),
        "chrome_start_error": (
            "Falha ao iniciar o Chrome/Selenium.",
            "O WebDriver não conseguiu criar ou conectar a sessão do navegador.",
            True,
        ),

        # LOGIN
        "login_credentials_error": (
            "Credenciais da Credtu não configuradas.",
            "DIALER_EMAIL ou DIALER_PASSWORD não estão disponíveis no ambiente.",
            False,
        ),
        "login_navigation_error": (
            "Falha ao abrir a página de login.",
            "O navegador não conseguiu navegar até a URL de login da Credtu.",
            True,
        ),
        "login_page_load_error": (
            "Página de login não terminou de carregar.",
            "O document.readyState não chegou a complete dentro do tempo esperado.",
            True,
        ),
        "login_email_field_not_found": (
            "Campo de e-mail não apareceu na tela de login.",
            "A página abriu, mas o formulário esperado não ficou disponível.",
            True,
        ),
        "login_email_field_error": (
            "Erro ao localizar o campo de e-mail.",
            "O Selenium falhou durante a leitura do campo de e-mail.",
            True,
        ),
        "login_email_fill_error": (
            "Erro ao preencher o e-mail.",
            "O campo foi localizado, mas clear/send_keys falhou.",
            True,
        ),
        "login_password_field_error": (
            "Erro ao localizar o campo de senha.",
            "O campo de senha não ficou disponível ou sofreu re-renderização.",
            True,
        ),
        "login_password_fill_error": (
            "Erro ao preencher a senha.",
            "O campo de senha foi localizado, mas clear/send_keys falhou.",
            True,
        ),
        "login_button_not_clickable": (
            "Botão Entrar não ficou clicável.",
            "O botão de login não apareceu habilitado dentro do timeout.",
            True,
        ),
        "login_button_click_error": (
            "Falha ao clicar em Entrar.",
            "O botão foi localizado, mas o clique Selenium/JavaScript falhou.",
            True,
        ),
        "login_redirect_error": (
            "Login não concluiu o redirecionamento.",
            "A autenticação não saiu da tela de login dentro do tempo esperado.",
            True,
        ),
        "login_post_load_error": (
            "Página pós-login não terminou de carregar.",
            "A autenticação avançou, mas o carregamento final não estabilizou.",
            True,
        ),

        # 2FA / TOTP
        "totp_secret_missing": (
            "Secret do TOTP não configurada.",
            "DIALER_TOTP_SECRET não está disponível no ambiente.",
            False,
        ),
        "totp_generate_error": (
            "Falha ao gerar o código TOTP.",
            "A biblioteca pyotp não conseguiu gerar o código atual.",
            True,
        ),
        "totp_invalid_code": (
            "Código TOTP gerado em formato inesperado.",
            "O valor gerado não possui exatamente 6 dígitos.",
            True,
        ),
        "two_factor_detect_error": (
            "Erro ao verificar se a tela de 2FA apareceu.",
            "A leitura da tela de autenticação em duas etapas falhou.",
            True,
        ),
        "two_factor_input_not_found": (
            "Campo do código 2FA não foi encontrado.",
            "A tela de 2FA apareceu, mas o campo TOTP não ficou disponível.",
            True,
        ),
        "two_factor_fill_error": (
            "Falha ao preencher o código 2FA.",
            "O campo TOTP foi localizado, mas o código não pôde ser digitado.",
            True,
        ),
        "two_factor_button_not_found": (
            "Botão Avançar do 2FA não foi encontrado.",
            "O código foi preenchido, mas o botão de envio não ficou disponível.",
            True,
        ),
        "two_factor_submit_error": (
            "Falha ao enviar o código 2FA.",
            "O botão Avançar foi localizado, mas o clique falhou.",
            True,
        ),
        "two_factor_validation_timeout": (
            "A 3C não concluiu a validação do 2FA.",
            "A tela de autenticação permaneceu aberta após o envio do código.",
            True,
        ),

        # MODAL PÓS LOGIN
        "post_login_modal_detect_error": (
            "Erro ao verificar a janela opcional pós-login.",
            "A automação não conseguiu determinar o estado da janela pós-login.",
            True,
        ),
        "post_login_modal_click_error": (
            "Falha ao clicar na janela opcional pós-login.",
            "A janela apareceu, mas o botão não pôde ser acionado.",
            True,
        ),
        "post_login_modal_close_error": (
            "Janela pós-login não confirmou fechamento.",
            "O botão foi clicado, mas a janela permaneceu detectável.",
            True,
        ),

        # CAMPANHA
        "campaign_navigation_error": (
            "Falha ao abrir a campanha.",
            "O navegador não conseguiu navegar para a URL da campanha.",
            True,
        ),
        "campaign_page_load_error": (
            "Página da campanha não terminou de carregar.",
            "O document.readyState não chegou a complete dentro do timeout.",
            True,
        ),
        "campaign_current_url_error": (
            "Não foi possível ler a URL atual da campanha.",
            "A sessão do navegador apresentou erro ao consultar current_url.",
            True,
        ),
        "campaign_session_expired": (
            "Sessão da Credtu não permaneceu autenticada.",
            "Ao abrir a campanha, o navegador voltou para /login.",
            True,
        ),
        "campaign_wrong_url": (
            "Campanha abriu em uma URL diferente da esperada.",
            "Após a navegação, a URL atual não corresponde ao campaign_id solicitado.",
            True,
        ),

        # URA
        "ura_refresh_error": (
            "Falha ao atualizar a campanha durante recuperação da URA.",
            "O refresh do navegador falhou.",
            True,
        ),
        "ura_refresh_load_error": (
            "Campanha não terminou de carregar após refresh.",
            "O refresh ocorreu, mas a página não estabilizou dentro do timeout.",
            True,
        ),
        "ura_tab_not_found_after_refresh": (
            "Aba URA não foi encontrada mesmo após refresh.",
            "A interface da campanha não apresentou a aba URA esperada.",
            True,
        ),
        "ura_tab_locate_error": (
            "Erro técnico ao localizar a aba URA.",
            "O Selenium falhou durante a procura da aba.",
            True,
        ),
        "ura_tab_click_error": (
            "Falha ao clicar na aba URA.",
            "A aba foi localizada, mas o clique falhou.",
            True,
        ),
        "ura_content_load_error": (
            "Conteúdo da aba URA não apareceu.",
            "O clique ocorreu, mas o botão/listagem esperada da URA não ficou disponível.",
            True,
        ),

        # LISTAS
        "lists_button_not_found": (
            "Botão para abrir todas as listas não foi encontrado.",
            "A aba URA abriu, mas o controle de listagem não ficou clicável.",
            True,
        ),
        "lists_button_click_error": (
            "Falha ao abrir todas as listas.",
            "O botão foi encontrado, mas o clique falhou.",
            True,
        ),
        "lists_table_load_error": (
            "Tabela de listas não carregou.",
            "O tbody esperado não apareceu após abrir todas as listas.",
            True,
        ),
        "list_rows_load_error": (
            "Nenhuma linha visível apareceu na tabela.",
            "A tabela existe, mas não apresentou uma lista visível dentro do timeout.",
            True,
        ),
        "latest_list_read_error": (
            "Falha ao ler as listas visíveis.",
            "O Selenium encontrou a tabela, mas falhou ao obter as linhas.",
            True,
        ),
        "latest_list_not_found": (
            "Última lista da URA não foi encontrada.",
            "Não havia nenhuma linha visível para selecionar.",
            True,
        ),
        "latest_list_options_cell_error": (
            "Coluna de opções da última lista não foi encontrada.",
            "A última linha existe, mas td[10] não pôde ser localizado.",
            True,
        ),
        "latest_list_options_button_error": (
            "Botão de opções da última lista não foi localizado.",
            "A coluna de opções existe, mas o botão interno não pôde ser lido.",
            True,
        ),
        "latest_list_options_click_error": (
            "Falha ao abrir as opções da última lista.",
            "O botão de opções foi localizado, mas o clique falhou.",
            True,
        ),

        # RECICLAGEM
        "recycle_exclusion_modal_detect_error": (
            "Erro ao verificar a janela de exclusão da URA.",
            "A automação não conseguiu determinar se o modal de exclusão apareceu.",
            True,
        ),
        "recycle_exclusion_modal_click_error": (
            "Falha ao cancelar a janela de exclusão.",
            "O botão CANCELAR foi detectado, mas o clique falhou.",
            True,
        ),
        "recycle_exclusion_modal_close_error": (
            "Janela de exclusão não confirmou fechamento.",
            "Foi clicado em CANCELAR, mas o modal permaneceu visível além do timeout.",
            True,
        ),
        "recycle_options_reopen_error": (
            "Falha ao relocalizar/reabrir as opções da última lista.",
            "A referência da linha ficou inválida e a recuperação anti-stale não conseguiu reabrir o menu.",
            True,
        ),
        "recycle_button_not_found": (
            "Botão Reciclar não foi encontrado.",
            "O botão não apareceu nem pelo XPath principal nem pelos fallbacks de recuperação.",
            True,
        ),
        "recycle_button_click_error": (
            "Falha ao clicar no botão Reciclar.",
            "O botão foi localizado, mas o clique falhou mesmo após a recuperação disponível.",
            True,
        ),
        "recycle_screen_load_error": (
            "Tela de reciclagem não carregou após o clique.",
            "O clique em Reciclar ocorreu, mas o elemento do nome da lista não apareceu dentro do timeout.",
            True,
        ),

        # NOME
        "current_list_name_element_error": (
            "Elemento do nome atual da lista não foi encontrado.",
            "A tela de reciclagem abriu, mas o elemento esperado do nome não ficou disponível.",
            True,
        ),
        "current_list_name_read_error": (
            "Falha ao ler o nome atual da lista.",
            "O elemento existe, mas a leitura do texto falhou.",
            True,
        ),
        "current_list_name_empty": (
            "Nome atual da lista veio vazio.",
            "O elemento foi localizado, porém sem texto utilizável.",
            True,
        ),
        "new_list_name_generate_error": (
            "Falha ao gerar o nome da próxima REC.",
            "O nome atual não possui o padrão REC esperado ou não pôde ser processado.",
            False,
        ),
        "list_name_input_not_found": (
            "Campo do novo nome não foi encontrado.",
            "A tela de reciclagem abriu, mas o input do novo nome não ficou clicável.",
            True,
        ),
        "list_name_input_click_error": (
            "Falha ao clicar no campo do novo nome.",
            "O input foi encontrado, mas não recebeu foco.",
            True,
        ),
        "list_name_input_clear_error": (
            "Falha ao limpar o campo do novo nome.",
            "O campo recebeu foco, mas Ctrl+A/Backspace falhou.",
            True,
        ),
        "list_name_input_type_error": (
            "Falha ao digitar o novo nome.",
            "O campo foi limpo, mas send_keys do novo nome falhou.",
            True,
        ),
        "list_name_input_verify_error": (
            "Novo nome não ficou preenchido como esperado.",
            "O valor final do input não corresponde ao nome gerado.",
            True,
        ),

        # CONFIRMAÇÃO FINAL
        "recycle_confirm_button_not_found": (
            "Botão final de Reciclar não foi encontrado.",
            "A tela foi preenchida, mas o botão de confirmação não ficou clicável.",
            True,
        ),
        "recycle_confirm_click_error": (
            "Falha no clique final de Reciclar.",
            "O botão final foi localizado, mas o clique falhou.",
            True,
        ),

        "unexpected_error": (
            "Erro inesperado fora das etapas mapeadas.",
            "Ocorreu uma exceção não prevista pelo tratamento específico atual.",
            True,
        ),
    }

    # Checkboxes possuem status dinâmico:
    # checkbox_1_not_found, checkbox_4_click_error, etc.
    if str(status).startswith("checkbox_"):
        if str(status).endswith("_not_found"):
            return (
                "Checkbox de reciclagem não foi encontrado.",
                "O input esperado não apareceu na tela de reciclagem.",
                True,
            )
        if str(status).endswith("_state_error"):
            return (
                "Falha ao ler o estado do checkbox.",
                "O Selenium não conseguiu confirmar se a opção estava marcada.",
                True,
            )
        if str(status).endswith("_click_error"):
            return (
                "Falha ao marcar o checkbox.",
                "O clique normal e/ou JavaScript não conseguiu alterar a opção.",
                True,
            )
        if str(status).endswith("_verify_error"):
            return (
                "Checkbox não confirmou estado marcado.",
                "Após o clique, a opção não apareceu como selecionada dentro do timeout.",
                True,
            )

    if status in mapa:
        return mapa[status]

    # Fallback apenas de diagnóstico.
    return (
        f"Falha na etapa {stage}.",
        f"Erro {error_type}: {message}",
        True,
    )


def _diagnostic_status(status, stage, error_type):
    return "__".join(
        [
            _normalizar_codigo_diagnostico(status),
            _normalizar_codigo_diagnostico(stage),
            _normalizar_codigo_diagnostico(error_type),
        ]
    )


def _coletar_contexto_driver(driver):
    """
    Coleta SOMENTE informações de leitura após uma falha.
    Não clica, não navega e não modifica o DOM.
    """
    contexto = {}

    try:
        contexto["current_url"] = str(driver.current_url)
    except Exception as erro:
        contexto["current_url_error"] = (
            f"{type(erro).__name__}: {erro}"
        )

    try:
        contexto["page_title"] = str(driver.title)
    except Exception as erro:
        contexto["page_title_error"] = (
            f"{type(erro).__name__}: {erro}"
        )

    try:
        contexto["ready_state"] = str(
            driver.execute_script(
                "return document.readyState"
            )
        )
    except Exception as erro:
        contexto["ready_state_error"] = (
            f"{type(erro).__name__}: {erro}"
        )

    try:
        contexto["window_count"] = len(
            driver.window_handles
        )
    except Exception as erro:
        contexto["window_count_error"] = (
            f"{type(erro).__name__}: {erro}"
        )

    # Estado de elementos-chave no instante da falha.
    elementos = {
        "login_email": XPATH_EMAIL,
        "post_login_modal_button": XPATH_BOTAO_JANELA_POS_LOGIN,
        "ura_tab": XPATH_ABA_URA,
        "lists_table": XPATH_TBODY_LISTAS,
        "recycle_current_name": XPATH_NOME_LISTA_ATUAL,
        "recycle_exclusion_cancel": XPATH_FECHAR_JANELA_EXCLUSAO,
        "recycle_final_button": XPATH_BOTAO_FINAL_RECICLAR,
    }

    dom = {}

    for nome, xpath in elementos.items():
        try:
            encontrados = driver.find_elements(
                By.XPATH,
                xpath,
            )

            visiveis = 0

            for elemento in encontrados:
                try:
                    if elemento.is_displayed():
                        visiveis += 1
                except Exception:
                    pass

            dom[nome] = {
                "found": len(encontrados),
                "visible": visiveis,
            }
        except Exception as erro:
            dom[nome] = {
                "error": (
                    f"{type(erro).__name__}: {erro}"
                )
            }

    # 2FA possui vários seletores possíveis.
    try:
        campo_2fa = _primeiro_elemento_visivel(
            driver,
            XPATHS_CAMPO_2FA,
            exigir_clicavel=False,
        )
        botao_2fa = _primeiro_elemento_visivel(
            driver,
            XPATHS_BOTAO_2FA,
            exigir_clicavel=False,
        )
        dom["two_factor"] = {
            "screen_visible": bool(
                _pagina_2fa_visivel(driver)
            ),
            "input_visible": bool(campo_2fa),
            "button_visible": bool(botao_2fa),
        }
    except Exception as erro:
        dom["two_factor"] = {
            "error": (
                f"{type(erro).__name__}: {erro}"
            )
        }

    contexto["dom_state"] = dom

    return contexto


def _traceback_resumido():
    """
    Retorna somente o final do traceback para evitar respostas gigantes no n8n.
    Não inclui valores de variáveis locais.
    """
    try:
        linhas = [
            linha
            for linha in traceback.format_exc().splitlines()
            if linha.strip()
        ]

        resumo = "\n".join(
            linhas[-12:]
        )

        return resumo[-3000:]

    except Exception:
        return ""


class CredtuAutomationError(Exception):
    """
    Erro estruturado da automação.

    As chaves originais continuam existindo para manter compatibilidade
    com o main.py e com o n8n.

    Campos adicionais são SOMENTE diagnósticos.
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

        # Contexto preenchido apenas quando ocorre falha.
        self.context = {}
        self.traceback_tail = ""

        super().__init__(
            f"[{status}] {stage}: "
            f"{self.error_type}: {self.message}"
        )

    def add_context(self, **dados):
        """
        Acrescenta dados de diagnóstico sem alterar status/stage originais.
        """
        for chave, valor in dados.items():
            if valor is not None:
                self.context[chave] = valor

        return self

    def to_dict(self):
        resumo, causa, retry = _descricao_erro(
            self.status,
            self.stage,
            self.error_type,
            self.message,
        )

        resposta = {
            # CAMPOS ORIGINAIS - NÃO ALTERADOS
            "ok": False,
            "status": self.status,
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,

            # CAMPOS NOVOS - SOMENTE DIAGNÓSTICO
            "diagnostic_status": _diagnostic_status(
                self.status,
                self.stage,
                self.error_type,
            ),
            "error_summary": resumo,
            "likely_cause": causa,
            "retry_recommended": retry,
        }

        if self.context:
            resposta["context"] = self.context

        if self.traceback_tail:
            resposta["traceback_tail"] = self.traceback_tail

        return resposta


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

    Após uma etapa bem-sucedida, aplica uma pausa curta para
    evitar que a próxima macro-etapa comece durante uma
    re-renderização da interface.

    Os acréscimos abaixo são SOMENTE de log/diagnóstico.
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

        atraso = _delay_etapa()

        if atraso > 0:
            log(
                f"[ETAPA] ESTABILIZAÇÃO | "
                f"stage={stage} | pausa={atraso:g}s"
            )
            time.sleep(atraso)

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
            f"diagnostic_status="
            f"{_diagnostic_status(erro.status, erro.stage, erro.error_type)} | "
            f"error_type={erro.error_type} | "
            f"message={erro.message}"
        )
        raise

    except Exception as erro:
        erro_estruturado = CredtuAutomationError(
            status=status,
            stage=stage,
            original_error=erro,
        )

        log(
            f"[ETAPA] ERRO GENÉRICO | "
            f"stage={stage} | "
            f"status={status} | "
            f"diagnostic_status="
            f"{_diagnostic_status(status, stage, type(erro).__name__)} | "
            f"error_type={type(erro).__name__} | "
            f"message={str(erro).strip() or type(erro).__name__}"
        )

        raise erro_estruturado from erro


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

# Janela opcional que pode aparecer logo após o login.
XPATH_BOTAO_JANELA_POS_LOGIN = (
    "/html/body/div[1]/div[2]/div/div[1]/div/div/div[2]/div[5]/button"
)

# Tela opcional de autenticação em dois fatores (TOTP).
# Os seletores usam o texto oficial da tela e fallbacks por atributos
# comuns de campos de código, para evitar depender de um único XPath absoluto.
XPATH_2FA_TITULO = (
    "//*[contains(normalize-space(.), 'Verificação em duas etapas')]"
)

XPATHS_CAMPO_2FA = [
    "//input[@autocomplete='one-time-code']",
    "//input[@inputmode='numeric' and @maxlength='6']",
    "//input[@maxlength='6']",
    "//label[contains(normalize-space(.), 'Insira o código')]/following::input[1]",
]

XPATHS_BOTAO_2FA = [
    "//button[normalize-space(.)='Avançar']",
    (
        "//button[contains("
        "translate(normalize-space(.),"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ',"
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç'),"
        "'avançar')]"
    ),
]


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

# No Discador permanecemos na aba padrão "Listas".
# O botão "mostrar todas as listas" ocupa a mesma posição estrutural
# confirmada no ambiente atual.
XPATH_ABRIR_TODAS_LISTAS_DIALER = XPATH_ABRIR_TODAS_LISTAS_URA


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

# Discador: esta opção também deve ser marcada.
XPATH_CHECKBOX_2 = (
    "/html/body/div[1]/div[2]/div[1]/div[2]/div/div[4]/"
    "div/div/div[2]/div[1]/div[1]/div/div[2]/div/div/div[2]/input"
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
    ("checkbox 2", XPATH_CHECKBOX_2),
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


def _delay_acao():
    """Pequena pausa após ações que alteram a interface."""
    return float(os.getenv("AUTOMATION_ACTION_DELAY_SECONDS", "0.7"))


def _delay_etapa():
    """Pausa curta entre macro-etapas da automação."""
    return float(os.getenv("AUTOMATION_STAGE_DELAY_SECONDS", "0.35"))


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
    """Executa o clique e aguarda uma curta estabilização do frontend."""
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
        driver.execute_script(
            "arguments[0].click();",
            elemento,
        )

    atraso = _delay_acao()
    if atraso > 0:
        time.sleep(atraso)


def texto_elemento(elemento):
    return str(
        elemento.text
        or elemento.get_attribute("textContent")
        or elemento.get_attribute("innerText")
        or ""
    ).strip()


def _primeiro_elemento_visivel(driver, xpaths, exigir_clicavel=False):
    """Retorna o primeiro elemento visível encontrado entre vários XPaths."""
    for xpath in xpaths:
        try:
            elementos = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue

        for elemento in elementos:
            try:
                if not elemento.is_displayed():
                    continue
                if exigir_clicavel and not elemento.is_enabled():
                    continue
                return elemento
            except StaleElementReferenceException:
                continue

    return False


def _pagina_2fa_visivel(driver):
    """Detecta a tela de verificação em duas etapas sem depender da URL."""
    try:
        titulos = driver.find_elements(By.XPATH, XPATH_2FA_TITULO)
        for titulo in titulos:
            try:
                if titulo.is_displayed():
                    return True
            except StaleElementReferenceException:
                continue
    except Exception:
        pass

    campo = _primeiro_elemento_visivel(
        driver,
        XPATHS_CAMPO_2FA,
        exigir_clicavel=False,
    )
    botao = _primeiro_elemento_visivel(
        driver,
        XPATHS_BOTAO_2FA,
        exigir_clicavel=False,
    )

    return bool(campo and botao)


def _gerar_codigo_totp():
    """Gera o código TOTP atual usando a secret configurada no .env."""
    secret = str(
        os.getenv("DIALER_TOTP_SECRET", "")
    ).strip().replace(" ", "")

    if not secret:
        raise CredtuAutomationError(
            status="totp_secret_missing",
            stage="load_totp_secret",
            original_error=RuntimeError(
                "DIALER_TOTP_SECRET não está configurada no .env."
            ),
        )

    try:
        totp = pyotp.TOTP(secret)

        # Evita enviar um código quando faltam poucos segundos para expirar.
        restante = totp.interval - (int(time.time()) % totp.interval)
        if restante <= 3:
            log(
                "[AÇÃO 2FA] Código TOTP perto de expirar. "
                "Aguardando a próxima janela de 30 segundos..."
            )
            time.sleep(restante + 1)

        codigo = str(totp.now()).strip()

    except CredtuAutomationError:
        raise
    except Exception as erro:
        raise CredtuAutomationError(
            status="totp_generate_error",
            stage="generate_totp_code",
            original_error=erro,
        ) from erro

    if not re.fullmatch(r"\d{6}", codigo):
        raise CredtuAutomationError(
            status="totp_invalid_code",
            stage="validate_totp_code",
            original_error=RuntimeError(
                "A biblioteca TOTP não gerou um código de 6 dígitos."
            ),
        )

    # Nunca registrar a secret nem o código no log.
    log("[OK 2FA] Código TOTP de 6 dígitos gerado.")
    return codigo


def verificar_2fa_se_aparecer(driver, timeout=8):
    """
    Detecta e resolve a verificação 2FA/TOTP quando a 3C solicitar.

    Se a tela não aparecer, retorna False e o login continua normalmente.
    Se aparecer, gera o código com pyotp, preenche, avança e aguarda a tela sair.
    """
    log("[AÇÃO 2FA] Verificando se a autenticação em duas etapas foi solicitada...")

    try:
        WebDriverWait(
            driver,
            timeout,
            poll_frequency=0.2,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: _pagina_2fa_visivel(d)
        )
    except TimeoutException:
        log("[OK 2FA] Tela 2FA não apareceu. Seguindo sem código TOTP.")
        return False
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_detect_error",
            stage="detect_two_factor_screen",
            original_error=erro,
        ) from erro

    log("[AVISO 2FA] Tela de verificação em duas etapas detectada.")

    codigo = _gerar_codigo_totp()

    log("[AÇÃO 2FA] Procurando campo do código de autenticação...")
    try:
        campo = WebDriverWait(
            driver,
            10,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: _primeiro_elemento_visivel(
                d,
                XPATHS_CAMPO_2FA,
                exigir_clicavel=True,
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_input_not_found",
            stage="locate_two_factor_input",
            original_error=erro,
        ) from erro

    log("[OK 2FA] Campo do código encontrado.")
    log("[AÇÃO 2FA] Preenchendo código TOTP...")

    try:
        campo.click()
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.BACKSPACE)
        campo.send_keys(codigo)
    except StaleElementReferenceException:
        try:
            campo = WebDriverWait(
                driver,
                5,
                poll_frequency=0.1,
                ignored_exceptions=(StaleElementReferenceException,),
            ).until(
                lambda d: _primeiro_elemento_visivel(
                    d,
                    XPATHS_CAMPO_2FA,
                    exigir_clicavel=True,
                )
            )
            campo.send_keys(Keys.CONTROL, "a")
            campo.send_keys(Keys.BACKSPACE)
            campo.send_keys(codigo)
        except Exception as erro:
            raise CredtuAutomationError(
                status="two_factor_fill_error",
                stage="fill_two_factor_code_after_stale",
                original_error=erro,
            ) from erro
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_fill_error",
            stage="fill_two_factor_code",
            original_error=erro,
        ) from erro

    log("[OK 2FA] Código TOTP preenchido.")
    log("[AÇÃO 2FA] Procurando botão Avançar...")

    try:
        botao = WebDriverWait(
            driver,
            10,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: _primeiro_elemento_visivel(
                d,
                XPATHS_BOTAO_2FA,
                exigir_clicavel=True,
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_button_not_found",
            stage="locate_two_factor_submit_button",
            original_error=erro,
        ) from erro

    log("[OK 2FA] Botão Avançar encontrado.")
    log("[AÇÃO 2FA] Enviando código de autenticação...")

    try:
        clicar(driver, botao)
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_submit_error",
            stage="submit_two_factor_code",
            original_error=erro,
        ) from erro

    log("[OK 2FA] Código enviado. Aguardando validação da 3C...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: not _pagina_2fa_visivel(d)
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="two_factor_validation_timeout",
            stage="wait_two_factor_validation",
            original_error=RuntimeError(
                "A tela de 2FA permaneceu aberta após o envio do código. "
                "O código pode ter sido recusado ou a página não concluiu a validação."
            ),
        ) from erro

    log("[OK 2FA] Verificação em duas etapas concluída.")
    return True


def fechar_janela_pos_login_se_aparecer(driver):
    """
    Fecha a janela opcional pós-login caso apareça.
    Se não aparecer em até 5 segundos, segue normalmente.
    """
    log("[AÇÃO LOGIN] Verificando janela opcional pós-login...")

    try:
        botao = WebDriverWait(
            driver,
            5,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: next(
                (
                    el
                    for el in d.find_elements(
                        By.XPATH,
                        XPATH_BOTAO_JANELA_POS_LOGIN,
                    )
                    if el.is_displayed() and el.is_enabled()
                ),
                False,
            )
        )
    except TimeoutException:
        log(
            "[OK LOGIN] Janela pós-login não apareceu. "
            "Seguindo normalmente."
        )
        return False
    except Exception as erro:
        raise CredtuAutomationError(
            status="post_login_modal_detect_error",
            stage="detect_post_login_modal",
            original_error=erro,
        ) from erro

    log("[AVISO LOGIN] Janela pós-login detectada.")
    log("[AÇÃO LOGIN] Clicando no botão da janela pós-login...")

    try:
        clicar(driver, botao)
    except StaleElementReferenceException:
        try:
            botao = esperar_clicavel(
                driver,
                XPATH_BOTAO_JANELA_POS_LOGIN,
                timeout=3,
            )
            clicar(driver, botao)
        except Exception as erro:
            raise CredtuAutomationError(
                status="post_login_modal_click_error",
                stage="click_post_login_modal_after_stale",
                original_error=erro,
            ) from erro
    except Exception as erro:
        raise CredtuAutomationError(
            status="post_login_modal_click_error",
            stage="click_post_login_modal",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Clique pós-login executado.")
    log("[AÇÃO LOGIN] Aguardando janela pós-login desaparecer...")

    try:
        WebDriverWait(
            driver,
            5,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: not any(
                el.is_displayed()
                for el in d.find_elements(
                    By.XPATH,
                    XPATH_BOTAO_JANELA_POS_LOGIN,
                )
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="post_login_modal_close_error",
            stage="wait_post_login_modal_close",
            original_error=erro,
        ) from erro

    log("[OK LOGIN] Janela pós-login fechada.")
    return True


def fazer_login(driver):
    email = str(os.getenv("DIALER_EMAIL", "")).strip()
    senha = str(os.getenv("DIALER_PASSWORD", "")).strip()

    if not email or not senha:
        raise CredtuAutomationError(
            status="login_credentials_error",
            stage="validate_login_credentials",
            original_error=RuntimeError(
                "DIALER_EMAIL e DIALER_PASSWORD precisam estar preenchidos no .env."
            ),
        )

    login_url = _dialer_login_url()

    log(f"[AÇÃO LOGIN DIALER] Abrindo tela de login: {login_url}")

    try:
        driver.get(login_url)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_navigation_error",
            stage="navigate_login_page",
            original_error=erro,
        ) from erro

    log("[AÇÃO LOGIN DIALER] Aguardando document.readyState=complete...")

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

    log("[OK LOGIN DIALER] Página carregada.")
    log("[AÇÃO LOGIN DIALER] Procurando campo de e-mail...")

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
            "[AVISO LOGIN DIALER] Campo de e-mail não apareceu, "
            "mas a URL não é mais /login. Considerando sessão já autenticada."
        )

        verificar_2fa_se_aparecer(
            driver,
            timeout=3,
        )
        fechar_janela_pos_login_se_aparecer(driver)
        return

    except Exception as erro:
        raise CredtuAutomationError(
            status="login_email_field_error",
            stage="locate_login_email_field",
            original_error=erro,
        ) from erro

    log("[AÇÃO LOGIN DIALER] Preenchendo e-mail...")

    try:
        campo_email.clear()
        campo_email.send_keys(email)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_email_fill_error",
            stage="fill_login_email",
            original_error=erro,
        ) from erro

    log("[AÇÃO LOGIN DIALER] Procurando campo de senha...")

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

    log("[AÇÃO LOGIN DIALER] Preenchendo senha...")

    try:
        campo_senha.clear()
        campo_senha.send_keys(senha)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_password_fill_error",
            stage="fill_login_password",
            original_error=erro,
        ) from erro

    log("[AÇÃO LOGIN DIALER] Procurando botão Entrar...")

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

    log("[AÇÃO LOGIN DIALER] Clicando em Entrar...")

    try:
        clicar(driver, botao_entrar)
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_button_click_error",
            stage="click_login_button",
            original_error=erro,
        ) from erro

    # O 2FA pode aparecer antes de a URL sair de /login.
    verificar_2fa_se_aparecer(
        driver,
        timeout=8,
    )

    log("[AÇÃO LOGIN DIALER] Aguardando autenticação concluir...")

    try:
        WebDriverWait(
            driver,
            _timeout(),
            poll_frequency=0.2,
        ).until(
            lambda d: (
                "/login" not in str(d.current_url).lower()
                and not _pagina_2fa_visivel(d)
            )
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="login_redirect_error",
            stage="wait_login_redirect_after_2fa",
            original_error=erro,
        ) from erro

    log(
        f"[OK LOGIN DIALER] Autenticação concluída. "
        f"URL atual: {driver.current_url}"
    )

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

    fechar_janela_pos_login_se_aparecer(
        driver
    )

    time.sleep(5)

    log("[OK LOGIN DIALER] Login concluído.")


def abrir_campanha(driver, campaign_id: str):
    url = f"{_dialer_base_url()}/manager/campaign/{campaign_id}"

    log(f"[AÇÃO CAMPANHA DIALER] Abrindo campanha {campaign_id}...")
    log(f"[DEBUG CAMPANHA DIALER] URL esperada: {url}")

    try:
        driver.get(url)
    except Exception as erro:
        raise CredtuAutomationError(
            status="campaign_navigation_error",
            stage="navigate_campaign",
            original_error=erro,
        ) from erro

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

    time.sleep(2)

    try:
        url_atual = str(driver.current_url)
    except Exception as erro:
        raise CredtuAutomationError(
            status="campaign_current_url_error",
            stage="read_campaign_current_url",
            original_error=erro,
        ) from erro

    log(f"[DEBUG CAMPANHA DIALER] URL atual: {url_atual}")

    if "/login" in url_atual.lower():
        raise CredtuAutomationError(
            status="campaign_session_expired",
            stage="validate_campaign_session",
            original_error=RuntimeError(
                "A sessão do Discador não permaneceu autenticada ao abrir a campanha."
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

    time.sleep(5)

    log("[OK CAMPANHA DIALER] Campanha correta aberta.")

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
    log("[AÇÃO DIALER] Procurando botão para mostrar todas as listas...")

    try:
        botao_listas = esperar_clicavel(
            driver,
            XPATH_ABRIR_TODAS_LISTAS_DIALER,
            timeout=45,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="dialer_lists_button_not_found",
            stage="locate_dialer_open_all_lists_button",
            original_error=erro,
        ) from erro

    log("[AÇÃO DIALER] Clicando para abrir todas as listas...")

    try:
        clicar(
            driver,
            botao_listas,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="dialer_lists_button_click_error",
            stage="click_dialer_open_all_lists_button",
            original_error=erro,
        ) from erro

    log("[AÇÃO DIALER] Aguardando tabela de listas renderizar...")

    try:
        esperar_elemento(
            driver,
            XPATH_TBODY_LISTAS,
            timeout=45,
        )
    except Exception as erro:
        raise CredtuAutomationError(
            status="dialer_lists_table_load_error",
            stage="wait_dialer_lists_table",
            original_error=erro,
        ) from erro

    log("[OK DIALER] Todas as listas carregadas.")

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


REC_PREFIX_RE = re.compile(
    r"^\s*REC\s*-?\s*(\d+)\s*(?:-|$)",
    flags=re.IGNORECASE,
)


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
                "Nenhuma lista do Discador foi encontrada."
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
    """
    Se a janela de exclusão da URA aparecer após o clique em Reciclar,
    clica em CANCELAR usando exatamente:

        /html/body/div[2]/div[2]/div[3]/button[1]

    O desaparecimento do elemento pode gerar stale enquanto o DOM é
    atualizado; isso é tratado como comportamento normal de fechamento.
    """
    log(
        "[AÇÃO RECICLAGEM] Verificando se apareceu "
        "janela de exclusão da URA..."
    )

    try:
        botao_cancelar = WebDriverWait(
            driver,
            3,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
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
        log(
            "[OK RECICLAGEM] Janela de exclusão da URA "
            "não apareceu. Seguindo normalmente."
        )
        return False
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_detect_error",
            stage="detect_recycle_exclusion_modal",
            original_error=erro,
        ) from erro

    log("[AVISO RECICLAGEM] Janela de exclusão da URA detectada.")
    log(
        "[AÇÃO RECICLAGEM] Clicando em CANCELAR exclusão "
        f"pelo XPath: {XPATH_FECHAR_JANELA_EXCLUSAO}"
    )

    try:
        clicar(driver, botao_cancelar)
    except StaleElementReferenceException:
        try:
            botao_cancelar = esperar_clicavel(
                driver,
                XPATH_FECHAR_JANELA_EXCLUSAO,
                timeout=3,
            )
            clicar(driver, botao_cancelar)
        except Exception as erro:
            raise CredtuAutomationError(
                status="recycle_exclusion_modal_click_error",
                stage="click_cancel_recycle_exclusion_after_stale",
                original_error=erro,
            ) from erro
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_click_error",
            stage="click_cancel_recycle_exclusion",
            original_error=erro,
        ) from erro

    log("[OK RECICLAGEM] Clique em CANCELAR exclusão executado.")
    log("[AÇÃO RECICLAGEM] Aguardando a janela de exclusão desaparecer...")

    def janela_ainda_visivel(d):
        try:
            elementos = d.find_elements(
                By.XPATH,
                XPATH_FECHAR_JANELA_EXCLUSAO,
            )
        except Exception:
            return False

        if not elementos:
            return False

        for elemento in elementos:
            try:
                if elemento.is_displayed():
                    return True
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
        return False

    try:
        WebDriverWait(
            driver,
            7,
            poll_frequency=0.15,
            ignored_exceptions=(StaleElementReferenceException,),
        ).until(
            lambda d: not janela_ainda_visivel(d)
        )
    except TimeoutException as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_close_error",
            stage="wait_recycle_exclusion_modal_close",
            original_error=RuntimeError(
                "Foi clicado em CANCELAR na janela de exclusão, "
                "mas ela continuou visível além do tempo esperado."
            ),
        ) from erro
    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_exclusion_modal_close_error",
            stage="wait_recycle_exclusion_modal_close",
            original_error=erro,
        ) from erro

    atraso = _delay_acao()
    if atraso > 0:
        time.sleep(atraso)

    log("[OK RECICLAGEM] Janela de exclusão cancelada e fechada.")
    return True


def clicar_reciclar(driver, ultima_linha):
    """
    Abre a reciclagem da última lista com recuperação de referências stale.

    Mantém a lógica original, mas:
    - tenta primeiro a referência recebida;
    - se a linha ficar stale, procura o botão globalmente;
    - se necessário, relocaliza a última lista e reabre as opções;
    - se o botão ficar stale no clique, relocaliza e tenta uma vez.
    """
    log("[AÇÃO RECICLAGEM] Abrindo reciclagem da última lista...")
    log("[AÇÃO RECICLAGEM] Procurando botão Reciclar pelo XPath principal da linha...")

    xpath_fallback = (
        "//button[contains("
        "translate(normalize-space(.),"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ',"
        "'abcdefghijklmnopqrstuvwxyzáàâãéêíóôõúç'),"
        "'reciclar')]"
    )

    botao_reciclar = None
    origem_botao = None

    try:
        botao_reciclar = WebDriverWait(
            driver,
            5,
            poll_frequency=0.1,
            ignored_exceptions=(StaleElementReferenceException,),
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
            f"[AVISO RECICLAGEM] A referência original da última linha "
            f"não localizou o botão Reciclar. "
            f"error_type={type(erro_principal).__name__} | erro={erro_principal}"
        )

        log(
            "[AÇÃO RECICLAGEM] Tentando localizar Reciclar "
            "globalmente antes de reabrir o menu..."
        )

        try:
            botao_reciclar = esperar_clicavel(
                driver,
                xpath_fallback,
                timeout=4,
            )
            origem_botao = "fallback_textual_pos_stale"
            log(
                "[OK RECICLAGEM] Botão Reciclar encontrado globalmente "
                "após perda da referência da linha."
            )

        except Exception as erro_fallback_1:
            log(
                f"[AVISO RECICLAGEM] Botão Reciclar não apareceu "
                f"globalmente na primeira recuperação. "
                f"error_type={type(erro_fallback_1).__name__} | erro={erro_fallback_1}"
            )

            log(
                "[AÇÃO RECICLAGEM] Relocalizando a última lista "
                "e reabrindo as opções..."
            )

            try:
                ultima_linha_atualizada = clicar_opcoes_da_ultima_lista(
                    driver
                )
            except Exception as erro_reabrir:
                raise CredtuAutomationError(
                    status="recycle_options_reopen_error",
                    stage="reopen_latest_list_options",
                    original_error=RuntimeError(
                        "A referência da última lista ficou inválida e "
                        "não foi possível relocalizar/reabrir suas opções. "
                        f"Erro inicial: {type(erro_principal).__name__}: "
                        f"{str(erro_principal).strip() or type(erro_principal).__name__}. "
                        f"Erro ao reabrir: {type(erro_reabrir).__name__}: "
                        f"{str(erro_reabrir).strip() or type(erro_reabrir).__name__}."
                    ),
                ) from erro_reabrir

            log(
                "[OK RECICLAGEM] Última lista relocalizada "
                "e opções reabertas."
            )

            try:
                botao_reciclar = esperar_clicavel(
                    driver,
                    xpath_fallback,
                    timeout=6,
                )
                origem_botao = "fallback_textual_apos_reabrir"
                log(
                    "[OK RECICLAGEM] Botão Reciclar encontrado "
                    "após relocalizar a última lista."
                )

            except Exception as erro_fallback_2:
                log(
                    "[AVISO RECICLAGEM] Fallback textual ainda não "
                    "localizou o botão. Tentando XPath principal "
                    "na nova referência da última linha..."
                )

                try:
                    botao_reciclar = WebDriverWait(
                        driver,
                        4,
                        poll_frequency=0.1,
                        ignored_exceptions=(StaleElementReferenceException,),
                    ).until(
                        lambda d: ultima_linha_atualizada.find_element(
                            By.XPATH,
                            "./td[10]/div/div/div/div[1]/button",
                        )
                    )
                    origem_botao = "xpath_principal_relocalizado"
                    log(
                        "[OK RECICLAGEM] Botão Reciclar encontrado "
                        "pela nova referência da última linha."
                    )

                except Exception as erro_final_localizacao:
                    raise CredtuAutomationError(
                        status="recycle_button_not_found",
                        stage="locate_recycle_button_after_recovery",
                        original_error=RuntimeError(
                            "Não foi possível localizar o botão Reciclar "
                            "mesmo após relocalizar a última lista e "
                            "reabrir suas opções. "
                            f"Erro referência original: "
                            f"{type(erro_principal).__name__}: "
                            f"{str(erro_principal).strip() or type(erro_principal).__name__}. "
                            f"Erro fallback inicial: "
                            f"{type(erro_fallback_1).__name__}: "
                            f"{str(erro_fallback_1).strip() or type(erro_fallback_1).__name__}. "
                            f"Erro fallback após reabrir: "
                            f"{type(erro_fallback_2).__name__}: "
                            f"{str(erro_fallback_2).strip() or type(erro_fallback_2).__name__}. "
                            f"Erro XPath relocalizado: "
                            f"{type(erro_final_localizacao).__name__}: "
                            f"{str(erro_final_localizacao).strip() or type(erro_final_localizacao).__name__}."
                        ),
                    ) from erro_final_localizacao

    log(
        f"[AÇÃO RECICLAGEM] Clicando no botão Reciclar. "
        f"origem={origem_botao}"
    )

    try:
        clicar(
            driver,
            botao_reciclar,
        )

    except StaleElementReferenceException as erro_stale_click:
        log(
            "[AVISO RECICLAGEM] O botão Reciclar ficou stale "
            "no momento do clique. Relocalizando o botão..."
        )

        try:
            botao_reciclar = esperar_clicavel(
                driver,
                xpath_fallback,
                timeout=5,
            )

            log(
                "[AÇÃO RECICLAGEM] Botão Reciclar relocalizado. "
                "Repetindo o clique uma única vez..."
            )

            clicar(
                driver,
                botao_reciclar,
            )

            origem_botao = "relocalizado_apos_stale_click"

        except Exception as erro_retry_click:
            raise CredtuAutomationError(
                status="recycle_button_click_error",
                stage="retry_click_recycle_button_after_stale",
                original_error=RuntimeError(
                    "O botão Reciclar ficou stale no primeiro clique "
                    "e a tentativa de relocalizar/clicar novamente falhou. "
                    f"Primeiro erro: "
                    f"{type(erro_stale_click).__name__}: "
                    f"{str(erro_stale_click).strip() or type(erro_stale_click).__name__}. "
                    f"Retry: "
                    f"{type(erro_retry_click).__name__}: "
                    f"{str(erro_retry_click).strip() or type(erro_retry_click).__name__}."
                ),
            ) from erro_retry_click

    except Exception as erro:
        raise CredtuAutomationError(
            status="recycle_button_click_error",
            stage="click_recycle_button",
            original_error=erro,
        ) from erro

    log(
        f"[OK RECICLAGEM] Clique no botão Reciclar executado. "
        f"origem_final={origem_botao}"
    )

    fechar_janela_exclusao_se_aparecer(
        driver
    )

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
    """
    Regra do Discador:

      LISTA TESTE.csv
      -> REC1 - LISTA TESTE | AUTO.R

      REC1 - LISTA TESTE | AUTO.R
      -> REC2 - LISTA TESTE | AUTO.R

    Regra de identificação:
    - se NÃO houver "REC" no nome, a lista é considerada original;
    - se houver "REC", ela é considerada uma lista reciclada;
    - para gerar a próxima REC, listas recicladas devem começar com REC<n>;
    - AUTO.R permanece no final das listas criadas automaticamente.

    Esta função não encerra o serviço/API. Qualquer erro de nome é tratado
    pelo fluxo estruturado da automação e devolvido ao n8n como erro da execução.
    """
    nome = str(nome_atual or "").strip()

    if not nome:
        raise RuntimeError(
            "O nome atual da lista está vazio."
        )

    # Remove somente o marcador criado pela própria automação.
    nome_sem_auto = re.sub(
        r"\s*\|\s*AUTO\.R\s*$",
        "",
        nome,
        flags=re.IGNORECASE,
    ).strip()

    # Regra solicitada:
    # se não existe "REC" em nenhum ponto do nome, é a lista original.
    contem_rec = "REC" in nome_sem_auto.upper()

    if not contem_rec:
        base = re.sub(
            r"\.csv\s*$",
            "",
            nome_sem_auto,
            flags=re.IGNORECASE,
        ).strip()

        if not base:
            raise RuntimeError(
                f"Não consegui extrair o nome base da lista: {nome_atual!r}"
            )

        return f"REC1 - {base} | AUTO.R"

    # Se contém REC, procuramos o padrão das listas geradas:
    # REC1 -, REC2 -, REC3 -, ...
    match = REC_PREFIX_RE.search(nome_sem_auto)

    if not match:
        raise RuntimeError(
            "A lista contém 'REC' no nome, portanto não é considerada "
            "original, mas também não começa com o padrão REC<n>. "
            f"Nome recebido: {nome_atual!r}"
        )

    numero_atual = int(match.group(1))
    proximo_numero = numero_atual + 1

    base = nome_sem_auto[match.end():].strip()

    # REC_PREFIX_RE pode terminar antes ou depois do hífen,
    # então removemos um hífen residual com segurança.
    base = re.sub(
        r"^\s*-\s*",
        "",
        base,
    ).strip()

    base = re.sub(
        r"\.csv\s*$",
        "",
        base,
        flags=re.IGNORECASE,
    ).strip()

    if not base:
        raise RuntimeError(
            f"Não consegui extrair o nome base da lista: {nome_atual!r}"
        )

    return f"REC{proximo_numero} - {base} | AUTO.R"


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
    Auto Reciclagem do Discador.

    IMPORTANTE:
    Este serviço NÃO decide se uma lista deve ou não ser reciclada.

    A decisão pertence ao fluxo do n8n.

    Sempre que o endpoint /api/recycle chamar esta função com um
    campaign_id válido, a automação seguirá diretamente para a
    reciclagem da lista mais atual da campanha.

    Fluxo:
      1. Chrome
      2. Login + 2FA
      3. Abre a campanha
      4. NÃO entra na aba URA
      5. Abre todas as listas
      6. Seleciona a lista mais atual
      7. Abre Reciclar
      8. Gera o próximo nome REC<n> ... | AUTO.R
      9. Marca checkboxes 1, 2, 4, 5 e 6
     10. Preenche o novo nome
     11. Confirma a reciclagem
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
            f" AUTO RECICLAGEM DISCAdor | "
            f"CAMPANHA {campaign_id}"
        )
        log("===================================================")

        # 1. Chrome
        driver = executar_etapa(
            "chrome_start_error",
            "dialer_open_chrome",
            criar_driver,
        )

        # 2. Login
        executar_etapa(
            "login_error",
            "dialer_login",
            fazer_login,
            driver,
        )

        # 3. Campanha
        executar_etapa(
            "campaign_open_error",
            "dialer_open_campaign",
            abrir_campanha,
            driver,
            campaign_id,
        )

        # O Discador permanece na aba LISTAS.
        # Não chama abrir_ura().
        log(
            "[DIALER] Campanha aberta. "
            "Permanecendo na aba LISTAS; aba URA não será acessada."
        )

        # 4. Abrir todas as listas
        executar_etapa(
            "dialer_lists_open_error",
            "dialer_open_all_lists",
            abrir_todas_listas,
            driver,
        )

        # Não existe condição de abandono, percentual restante ou
        # tamanho de lista aqui. Se o n8n chamou, devemos reciclar.
        log(
            "[DIALER] Solicitação recebida do n8n. "
            "Seguindo diretamente com a reciclagem."
        )

        # 5. Selecionar a lista mais atual
        ultima_linha = executar_etapa(
            "dialer_latest_list_error",
            "dialer_select_latest_list",
            clicar_opcoes_da_ultima_lista,
            driver,
        )

        # 6. Abrir reciclagem
        executar_etapa(
            "dialer_recycle_open_error",
            "dialer_open_recycle",
            clicar_reciclar,
            driver,
            ultima_linha,
        )

        # 7. Ler nome atual e gerar próxima REC
        nome_atual, novo_nome = executar_etapa(
            "dialer_list_name_error",
            "dialer_generate_list_name",
            obter_nome_atual_e_novo,
            driver,
        )

        # 8. Checkboxes do Discador: 1, 2, 4, 5 e 6
        executar_etapa(
            "dialer_checkbox_error",
            "dialer_mark_recycle_options",
            marcar_boxes_reciclagem,
            driver,
        )

        # 9. Preencher novo nome
        executar_etapa(
            "dialer_list_name_fill_error",
            "dialer_fill_new_list_name",
            preencher_novo_nome,
            driver,
            novo_nome,
        )

        # 10. Confirmar
        executar_etapa(
            "dialer_recycle_confirm_error",
            "dialer_confirm_recycle",
            finalizar_reciclagem,
            driver,
        )

        log(
            f"[DIALER] Reciclagem concluída: "
            f"{nome_atual!r} -> {novo_nome!r}"
        )

        return {
            "ok": True,
            "status": "success",
            "campaign_id": campaign_id,
            "recycled": True,
            "nome_anterior": nome_atual,
            "novo_nome": novo_nome,
        }

    except CredtuAutomationError as erro:
        if driver is not None:
            try:
                erro.add_context(
                    **_coletar_contexto_driver(
                        driver
                    )
                )
            except Exception as erro_contexto:
                erro.add_context(
                    context_collection_error=(
                        f"{type(erro_contexto).__name__}: "
                        f"{erro_contexto}"
                    )
                )

            prefixo_debug = (
                f"dialer_{erro.status}_{campaign_id}"
            )

            try:
                caminho_print = tirar_print_debug(
                    driver,
                    prefixo=prefixo_debug,
                )
                if caminho_print:
                    erro.add_context(
                        debug_screenshot_path=str(caminho_print)
                    )
            except Exception as erro_print:
                erro.add_context(
                    debug_screenshot_error=(
                        f"{type(erro_print).__name__}: {erro_print}"
                    )
                )

            try:
                caminho_html = salvar_html_debug(
                    driver,
                    prefixo=prefixo_debug,
                )
                if caminho_html:
                    erro.add_context(
                        debug_html_path=str(caminho_html)
                    )
            except Exception as erro_html:
                erro.add_context(
                    debug_html_error=(
                        f"{type(erro_html).__name__}: {erro_html}"
                    )
                )

        erro.traceback_tail = _traceback_resumido()

        log(
            "[ERRO FINAL DIALER] "
            f"status={erro.status} | "
            f"stage={erro.stage} | "
            f"diagnostic_status="
            f"{_diagnostic_status(erro.status, erro.stage, erro.error_type)} | "
            f"error_type={erro.error_type} | "
            f"message={erro.message}"
        )

        raise

    except Exception as erro:
        erro_estruturado = CredtuAutomationError(
            status="dialer_unexpected_error",
            stage="dialer_unknown",
            original_error=erro,
        )

        if driver is not None:
            try:
                erro_estruturado.add_context(
                    **_coletar_contexto_driver(
                        driver
                    )
                )
            except Exception:
                pass

            try:
                tirar_print_debug(
                    driver,
                    prefixo=f"dialer_unexpected_{campaign_id}",
                )
            except Exception:
                pass

            try:
                salvar_html_debug(
                    driver,
                    prefixo=f"dialer_unexpected_{campaign_id}",
                )
            except Exception:
                pass

        erro_estruturado.traceback_tail = _traceback_resumido()

        raise erro_estruturado from erro

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass