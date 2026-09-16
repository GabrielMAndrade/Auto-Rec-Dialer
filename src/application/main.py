import json
import os
import re
import secrets
import threading
import time
import traceback
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

import src.service.credtu_automation as automation


load_dotenv()


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Credtu Auto Reciclagem",
    version="2.1.0",
    description=(
        "Recebe somente o campaign_id do n8n "
        "e retorna somente true ou false."
    ),
)


# =========================================================
# LOCK
# =========================================================

automation_lock = threading.Lock()


# =========================================================
# REGEX
# =========================================================

REC_PREFIX_RE = re.compile(
    r"^\s*REC\s*-?\s*(\d+)\s*(?:-|$)",
    flags=re.IGNORECASE,
)

ORIGINAL_PREFIX_RE = re.compile(
    r"^\s*ORIG\.\s*",
    flags=re.IGNORECASE,
)


# =========================================================
# CONTEXTO DA EXECUÇÃO
# =========================================================

EXECUTION_CONTEXT = {}


ETAPAS = {
    "dialer_open_chrome": (
        1,
        "Abrindo Chrome/Selenium",
    ),

    "dialer_login": (
        2,
        "Realizando login + 2FA",
    ),

    "dialer_open_campaign": (
        3,
        "Abrindo campanha",
    ),

    "dialer_open_all_lists": (
        4,
        "Abrindo todas as listas",
    ),

    "dialer_select_latest_list": (
        5,
        "Identificando lista atual pelo nome",
    ),

    "dialer_open_recycle": (
        6,
        "Abrindo reciclagem",
    ),

    "dialer_generate_list_name": (
        7,
        "Lendo nome e gerando próxima REC",
    ),

    "dialer_mark_recycle_options": (
        8,
        "Marcando opções da reciclagem",
    ),

    "dialer_fill_new_list_name": (
        9,
        "Preenchendo novo nome",
    ),

    "dialer_confirm_recycle": (
        10,
        "Confirmando reciclagem",
    ),
}


# =========================================================
# LOG
# =========================================================

def log(mensagem):
    print(
        str(mensagem),
        flush=True,
    )


def reset_contexto(
    campaign_id,
):
    EXECUTION_CONTEXT.clear()

    EXECUTION_CONTEXT.update(
        {
            "campaign_id":
                str(campaign_id),

            "inicio":
                time.monotonic(),

            "etapa_atual":
                "API",

            "lista_atual":
                None,

            "lista_original":
                None,

            "novo_nome":
                None,

            "metricas":
                None,
        }
    )


# =========================================================
# TOKEN N8N
# =========================================================

def token_valido(
    authorization: str | None,
) -> bool:

    esperado = str(
        os.getenv(
            "N8N_API_TOKEN",
            "",
        )
    ).strip()

    if not esperado:
        log(
            "[ERRO API] "
            "N8N_API_TOKEN não está configurado."
        )

        return False

    recebido = ""

    if (
        authorization
        and authorization
        .lower()
        .startswith("bearer ")
    ):
        recebido = (
            authorization[7:]
            .strip()
        )

    if not recebido:
        log(
            "[ERRO API] "
            "Bearer Token não enviado."
        )

        return False

    return secrets.compare_digest(
        recebido,
        esperado,
    )


# =========================================================
# API 3C
#
# Usada SOMENTE para gerar o relatório.
#
# NÃO interfere na decisão do n8n.
# NÃO altera o contrato da API.
# =========================================================

def api_3c_token():

    for nome in (
        "DIALER_API_TOKEN",
        "THREEC_API_TOKEN",
        "C3_API_TOKEN",
        "API_3C_TOKEN",
    ):

        valor = str(
            os.getenv(
                nome,
                "",
            )
        ).strip()

        if valor:
            return valor

    return ""


def dialer_base_url():

    try:
        return (
            automation
            ._dialer_base_url()
        )

    except Exception:

        return str(
            os.getenv(
                "DIALER_BASE_URL",
                "https://somasoluoes.3c.plus",
            )
        ).strip().rstrip("/")


def nome_lista_api(
    item,
):

    return str(
        (item or {}).get(
            "name",
            "",
        )
    ).strip()


def id_lista_api(
    item,
):

    try:
        return int(
            (item or {}).get(
                "id",
                0,
            )
        )

    except Exception:
        return 0


# =========================================================
# ORIGINAL MAIS RECENTE
# =========================================================

def selecionar_original_api(
    listas,
):

    originais = []

    for indice, item in enumerate(
        listas
    ):

        nome = nome_lista_api(
            item
        )

        if ORIGINAL_PREFIX_RE.search(
            nome
        ):

            originais.append(
                (
                    indice,
                    item,
                )
            )

    if not originais:
        return None

    _, original = max(
        originais,
        key=lambda par: (
            id_lista_api(
                par[1]
            ),
            par[0],
        ),
    )

    return original


# =========================================================
# LISTA ATUAL PELA API
# =========================================================

def selecionar_atual_api(
    listas,
    original,
):

    recs = []

    for indice, item in enumerate(
        listas
    ):

        nome = nome_lista_api(
            item
        )

        match = REC_PREFIX_RE.search(
            nome
        )

        if not match:
            continue

        numero_rec = int(
            match.group(1)
        )

        recs.append(
            (
                numero_rec,
                id_lista_api(item),
                indice,
                item,
            )
        )

    if recs:

        return max(
            recs,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            ),
        )[3]

    return original


# =========================================================
# CONSULTA MÉTRICAS
# =========================================================

def consultar_metricas_3c(
    campaign_id,
):

    token = api_3c_token()

    if not token:

        log(
            "[AVISO RESUMO] "
            "DIALER_API_TOKEN não configurado. "
            "A reciclagem continuará normalmente, "
            "mas Qtd. original, Qtd. atual, "
            "restante e abandono ficarão como N/D."
        )

        return None

    query = urlencode(
        {
            "api_token":
                token,

            "per_page":
                "1500",

            "trashed[1]":
                "mailing_list",
        }
    )

    url = (
        f"{dialer_base_url()}"
        f"/api/v1/campaigns/"
        f"{campaign_id}"
        f"/lists?"
        f"{query}"
    )

    log(
        "[RESUMO] "
        "Consultando informações das listas..."
    )

    try:

        req = UrlRequest(
            url,
            headers={
                "Accept":
                    "application/json",

                "User-Agent":
                    "Auto-Recycle-Dialer/2.1",
            },
            method="GET",
        )

        with urlopen(
            req,
            timeout=30,
        ) as response:

            payload = json.loads(
                response
                .read()
                .decode(
                    "utf-8"
                )
            )

    except Exception as erro:

        log(
            "[AVISO RESUMO] "
            "Falha ao consultar API 3C: "
            f"{type(erro).__name__}: "
            f"{erro}"
        )

        return None

    listas = (
        payload.get(
            "data",
            [],
        )
        if isinstance(
            payload,
            dict,
        )
        else []
    )

    if not listas:

        log(
            "[AVISO RESUMO] "
            "Nenhuma lista retornada pela API."
        )

        return None

    original = selecionar_original_api(
        listas
    )

    if not original:

        log(
            "[AVISO RESUMO] "
            "Nenhuma lista iniciando com "
            "'ORIG.' encontrada."
        )

        return None

    atual = selecionar_atual_api(
        listas,
        original,
    )

    total_original = float(
        original.get(
            "total",
            0,
        )
        or 0
    )

    total_atual = float(
        atual.get(
            "total",
            0,
        )
        or 0
    )

    restante = None

    if total_original > 0:

        restante = (
            total_atual
            / total_original
            * 100
        )

    abandono = atual.get(
        "abandoned_percentage"
    )

    try:
        abandono = float(
            abandono
        )

    except Exception:
        abandono = None

    resultado = {
        "nome_original":
            nome_lista_api(
                original
            ),

        "nome_atual":
            nome_lista_api(
                atual
            ),

        "total_original":
            total_original,

        "total_atual":
            total_atual,

        "restante":
            restante,

        "abandono":
            abandono,
    }

    log(
        "[OK RESUMO] "
        f"Original={resultado['nome_original']!r} | "
        f"Atual={resultado['nome_atual']!r}"
    )

    return resultado


# =========================================================
# LÊ NOME DA LISTA NA LINHA
# =========================================================

def texto_lista_da_linha(
    linha,
):

    try:

        celulas = (
            linha.find_elements(
                automation.By.XPATH,
                "./td",
            )
        )

    except Exception:

        celulas = []

    for celula in celulas:

        try:

            texto = (
                automation
                .texto_elemento(
                    celula
                )
            )

        except Exception:

            continue

        texto = str(
            texto or ""
        ).strip()

        if not texto:
            continue

        if (
            REC_PREFIX_RE.search(
                texto
            )
            or
            ORIGINAL_PREFIX_RE.search(
                texto
            )
        ):

            return texto

    try:

        partes = [
            parte.strip()
            for parte in str(
                linha.text or ""
            ).splitlines()
            if parte.strip()
        ]

    except Exception:

        partes = []

    for texto in partes:

        if (
            REC_PREFIX_RE.search(
                texto
            )
            or
            ORIGINAL_PREFIX_RE.search(
                texto
            )
        ):

            return texto

    return ""


# =========================================================
# IDENTIFICA LISTA ATUAL PELO NOME
#
# REGRA:
#
# 1. procura todas REC<n>
# 2. pega o MAIOR número
# 3. se não existe REC:
#    usa ORIG. mais recente
#
# NÃO usa mais:
#
# linhas[-1]
# =========================================================

def selecionar_linha_atual(
    linhas,
):

    candidatos_rec = []
    candidatos_orig = []

    nome_atual_api = ""

    metricas = EXECUTION_CONTEXT.get(
        "metricas"
    )

    if isinstance(
        metricas,
        dict,
    ):

        nome_atual_api = str(
            metricas.get(
                "nome_atual",
                "",
            )
        ).strip()

    log(
        "[IDENTIFICAÇÃO] "
        f"Analisando {len(linhas)} listas..."
    )

    for indice, linha in enumerate(
        linhas
    ):

        nome = texto_lista_da_linha(
            linha
        )

        if not nome:

            log(
                "[IDENTIFICAÇÃO] "
                f"Linha {indice + 1}: "
                "ignorada."
            )

            continue

        log(
            "[IDENTIFICAÇÃO] "
            f"Linha {indice + 1}: "
            f"{nome!r}"
        )

        # Se temos dados da API,
        # tenta correspondência exata.
        if (
            nome_atual_api
            and
            nome.casefold()
            ==
            nome_atual_api.casefold()
        ):

            log(
                "[OK IDENTIFICAÇÃO] "
                "Lista atual localizada "
                "por correspondência exata."
            )

            return (
                linha,
                nome,
            )

        match_rec = (
            REC_PREFIX_RE.search(
                nome
            )
        )

        if match_rec:

            numero_rec = int(
                match_rec.group(1)
            )

            candidatos_rec.append(
                (
                    numero_rec,
                    indice,
                    nome,
                    linha,
                )
            )

            continue

        if ORIGINAL_PREFIX_RE.search(
            nome
        ):

            candidatos_orig.append(
                (
                    indice,
                    nome,
                    linha,
                )
            )

    # =====================================================
    # EXISTE REC
    # =====================================================

    if candidatos_rec:

        (
            numero,
            indice,
            nome,
            linha,
        ) = max(
            candidatos_rec,
            key=lambda item: (
                item[0],
                item[1],
            ),
        )

        log(
            "[OK IDENTIFICAÇÃO] "
            "Lista atual escolhida pelo maior REC. "
            f"REC{numero} | "
            f"linha={indice + 1} | "
            f"nome={nome!r}"
        )

        return (
            linha,
            nome,
        )

    # =====================================================
    # AINDA NÃO EXISTE REC
    # =====================================================

    if candidatos_orig:

        (
            indice,
            nome,
            linha,
        ) = max(
            candidatos_orig,
            key=lambda item:
                item[0],
        )

        log(
            "[OK IDENTIFICAÇÃO] "
            "Nenhuma REC encontrada. "
            "Usando ORIG. mais recente. "
            f"linha={indice + 1} | "
            f"nome={nome!r}"
        )

        return (
            linha,
            nome,
        )

    # =====================================================
    # NADA ENCONTRADO
    # =====================================================

    raise automation.CredtuAutomationError(
        status=
            "latest_list_not_found",

        stage=
            "select_current_list_by_name",

        original_error=
            RuntimeError(
                "Nenhuma lista elegível encontrada. "
                "A lista precisa começar com "
                "'ORIG.' ou 'REC<n> -'."
            ),
    )


# =========================================================
# ABRE OPÇÕES DA LISTA IDENTIFICADA
# =========================================================

def clicar_opcoes_da_lista_atual_por_nome(
    driver,
):

    automation.esperar_listas(
        driver
    )

    log(
        "[AÇÃO LISTA ATUAL] "
        "Identificando lista pelo nome..."
    )

    try:

        linhas = (
            automation
            .obter_linhas_visiveis(
                driver
            )
        )

    except Exception as erro:

        raise automation.CredtuAutomationError(
            status=
                "latest_list_read_error",

            stage=
                "read_visible_list_rows",

            original_error=
                erro,
        ) from erro

    if not linhas:

        raise automation.CredtuAutomationError(
            status=
                "latest_list_not_found",

            stage=
                "select_current_list_by_name",

            original_error=
                RuntimeError(
                    "Nenhuma lista encontrada."
                ),
        )

    linha_atual, nome_atual = (
        selecionar_linha_atual(
            linhas
        )
    )

    EXECUTION_CONTEXT[
        "lista_atual"
    ] = nome_atual

    # =====================================================
    # IDENTIFICA ORIG. PARA LOG
    # =====================================================

    originais = []

    for indice, linha in enumerate(
        linhas
    ):

        nome = texto_lista_da_linha(
            linha
        )

        if ORIGINAL_PREFIX_RE.search(
            nome
        ):

            originais.append(
                (
                    indice,
                    nome,
                )
            )

    if originais:

        _, nome_original = max(
            originais,
            key=lambda item:
                item[0],
        )

        EXECUTION_CONTEXT[
            "lista_original"
        ] = nome_original

    metricas = EXECUTION_CONTEXT.get(
        "metricas"
    )

    if (
        isinstance(
            metricas,
            dict,
        )
        and
        metricas.get(
            "nome_original"
        )
    ):

        EXECUTION_CONTEXT[
            "lista_original"
        ] = metricas[
            "nome_original"
        ]

    # =====================================================
    # COLUNA OPÇÕES
    # =====================================================

    log(
        "[AÇÃO LISTA ATUAL] "
        f"Abrindo opções de {nome_atual!r}"
    )

    try:

        celula_opcoes = (
            linha_atual
            .find_element(
                automation.By.XPATH,
                "./td[10]",
            )
        )

    except Exception as erro:

        raise automation.CredtuAutomationError(
            status=
                "latest_list_options_cell_error",

            stage=
                "locate_latest_list_options_cell",

            original_error=
                erro,
        ) from erro

    try:

        driver.execute_script(
            "arguments[0].scrollIntoView("
            "{block:'center', inline:'center'});",
            celula_opcoes,
        )

    except Exception as erro:

        log(
            "[AVISO LISTA ATUAL] "
            f"Scroll falhou: {erro}"
        )

    try:

        botoes = (
            celula_opcoes
            .find_elements(
                automation.By.XPATH,
                ".//button",
            )
        )

        botao_opcoes = (
            botoes[-1]
            if botoes
            else celula_opcoes
        )

    except Exception as erro:

        raise automation.CredtuAutomationError(
            status=
                "latest_list_options_button_error",

            stage=
                "locate_latest_list_options_button",

            original_error=
                erro,
        ) from erro

    try:

        automation.clicar(
            driver,
            botao_opcoes,
        )

    except Exception as erro:

        raise automation.CredtuAutomationError(
            status=
                "latest_list_options_click_error",

            stage=
                "click_latest_list_options",

            original_error=
                erro,
        ) from erro

    log(
        "[OK LISTA ATUAL] "
        f"Opções abertas para {nome_atual!r}"
    )

    return linha_atual


# =========================================================
# NOVO NOME
#
# ORIG. É OBRIGATÓRIO PARA CRIAR REC1
# =========================================================

def gerar_nome_proxima_reciclagem_segura(
    nome_atual,
):

    nome = str(
        nome_atual or ""
    ).strip()

    if not nome:

        raise RuntimeError(
            "Nome da lista vazio."
        )

    nome_sem_auto = re.sub(
        r"\s*\|\s*AUTO\.R\s*$",
        "",
        nome,
        flags=re.IGNORECASE,
    ).strip()

    # =====================================================
    # JÁ É REC
    # =====================================================

    match_rec = (
        REC_PREFIX_RE.search(
            nome_sem_auto
        )
    )

    if match_rec:

        numero_atual = int(
            match_rec.group(1)
        )

        base = nome_sem_auto[
            match_rec.end():
        ].strip()

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

        # Compatibilidade com nome antigo.
        base = ORIGINAL_PREFIX_RE.sub(
            "",
            base,
            count=1,
        ).strip()

        if not base:

            raise RuntimeError(
                "Não consegui extrair "
                "o nome base da lista."
            )

        novo_nome = (
            f"REC{numero_atual + 1} - "
            f"{base} | AUTO.R"
        )

        EXECUTION_CONTEXT[
            "novo_nome"
        ] = novo_nome

        return novo_nome

    # =====================================================
    # PRIMEIRA REC
    # =====================================================

    match_original = (
        ORIGINAL_PREFIX_RE.search(
            nome_sem_auto
        )
    )

    if not match_original:

        raise RuntimeError(
            "Lista não reconhecida para "
            "auto-reciclagem. "
            "Para criar REC1 o nome deve "
            "começar obrigatoriamente com "
            "'ORIG.'. "
            f"Nome recebido: {nome_atual!r}"
        )

    base = ORIGINAL_PREFIX_RE.sub(
        "",
        nome_sem_auto,
        count=1,
    ).strip()

    base = re.sub(
        r"\.csv\s*$",
        "",
        base,
        flags=re.IGNORECASE,
    ).strip()

    if not base:

        raise RuntimeError(
            "Não consegui extrair "
            "o nome base da lista."
        )

    novo_nome = (
        f"REC1 - {base} | AUTO.R"
    )

    EXECUTION_CONTEXT[
        "novo_nome"
    ] = novo_nome

    return novo_nome


# =========================================================
# LOG AUTOMÁTICO DAS ETAPAS
# =========================================================

ORIGINAL_EXECUTAR_ETAPA = (
    automation.executar_etapa
)


def executar_etapa_com_progresso(
    status,
    stage,
    funcao,
    *args,
    **kwargs,
):

    etapa = ETAPAS.get(
        stage
    )

    if etapa:

        numero, descricao = etapa

        EXECUTION_CONTEXT[
            "etapa_atual"
        ] = (
            f"{numero:02d}/10 - "
            f"{descricao}"
        )

        decorrido = (
            time.monotonic()
            -
            EXECUTION_CONTEXT.get(
                "inicio",
                time.monotonic(),
            )
        )

        log(
            f"[PROGRESSO "
            f"{numero:02d}/10 | "
            f"+{decorrido:.1f}s] "
            f"{descricao}"
        )

    else:

        EXECUTION_CONTEXT[
            "etapa_atual"
        ] = stage

    inicio_etapa = (
        time.monotonic()
    )

    try:

        resultado = (
            ORIGINAL_EXECUTAR_ETAPA(
                status,
                stage,
                funcao,
                *args,
                **kwargs,
            )
        )

        duracao = (
            time.monotonic()
            -
            inicio_etapa
        )

        log(
            "[ETAPA CONCLUÍDA] "
            f"{stage} | "
            f"duração={duracao:.1f}s"
        )

        return resultado

    except Exception:

        duracao_total = (
            time.monotonic()
            -
            EXECUTION_CONTEXT.get(
                "inicio",
                time.monotonic(),
            )
        )

        log(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        log(
            "[PAROU EM] "
            f"{EXECUTION_CONTEXT.get('etapa_atual')}"
        )

        log(
            "[TEMPO ATÉ O ERRO] "
            f"{duracao_total:.1f}s"
        )

        log(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        raise


# =========================================================
# APLICA AS MELHORIAS
#
# Não precisa alterar credtu_automation.py.
# =========================================================

automation.clicar_opcoes_da_ultima_lista = (
    clicar_opcoes_da_lista_atual_por_nome
)

automation.gerar_nome_proxima_reciclagem = (
    gerar_nome_proxima_reciclagem_segura
)

automation.executar_etapa = (
    executar_etapa_com_progresso
)


# =========================================================
# FORMATADORES DO RESUMO
# =========================================================

def formatar_numero(
    valor,
):

    if valor is None:
        return "N/D"

    try:

        numero = float(
            valor
        )

        if numero.is_integer():

            return str(
                int(numero)
            )

        return (
            f"{numero:.2f}"
            .rstrip("0")
            .rstrip(".")
        )

    except Exception:

        return str(
            valor
        )


def nome_rec_resumido(
    nome,
):

    texto = str(
        nome or ""
    ).strip()

    match = REC_PREFIX_RE.search(
        texto
    )

    if not match:

        return (
            texto
            if texto
            else "N/D"
        )

    return (
        f"REC{int(match.group(1))}"
    )


# =========================================================
# RESUMO FINAL
# =========================================================

def log_resumo_final(
    campaign_id,
    resultado,
):

    duracao = (
        time.monotonic()
        -
        EXECUTION_CONTEXT.get(
            "inicio",
            time.monotonic(),
        )
    )

    metricas = EXECUTION_CONTEXT.get(
        "metricas"
    )

    nome_atual = (
        EXECUTION_CONTEXT.get(
            "lista_atual"
        )
    )

    nome_original = (
        EXECUTION_CONTEXT.get(
            "lista_original"
        )
    )

    novo_nome = (
        EXECUTION_CONTEXT.get(
            "novo_nome"
        )
    )

    # credtu_automation atual pode devolver dict.
    if isinstance(
        resultado,
        dict,
    ):

        nome_atual = (
            resultado.get(
                "nome_anterior"
            )
            or nome_atual
        )

        novo_nome = (
            resultado.get(
                "novo_nome"
            )
            or novo_nome
        )

    total_original = None
    total_atual = None
    restante = None
    abandono = None

    if isinstance(
        metricas,
        dict,
    ):

        nome_original = (
            metricas.get(
                "nome_original"
            )
            or nome_original
        )

        total_original = (
            metricas.get(
                "total_original"
            )
        )

        total_atual = (
            metricas.get(
                "total_atual"
            )
        )

        restante = (
            metricas.get(
                "restante"
            )
        )

        abandono = (
            metricas.get(
                "abandono"
            )
        )

    horario = (
        datetime
        .now()
        .astimezone()
        .strftime(
            "%d/%m %H:%M"
        )
    )

    log("")
    log(
        "=============================================="
    )

    log(
        "[RESUMO FINAL AUTO-RECICLAGEM]"
    )

    log(
        "=============================================="
    )

    log(
        horario
    )

    log(
        f"Campanha: {campaign_id}"
    )

    log(
        f"Atual: "
        f"{nome_atual or 'N/D'}"
    )

    log(
        f"Original: "
        f"{nome_original or 'N/D'}"
    )

    log(
        "Qtd. original: "
        f"{formatar_numero(total_original)}"
    )

    log(
        "Qtd. atual: "
        f"{formatar_numero(total_atual)}"
    )

    if isinstance(
        restante,
        (int, float),
    ):

        log(
            f"Restante: "
            f"{restante:.2f}%"
        )

    else:

        log(
            "Restante: N/D"
        )

    if isinstance(
        abandono,
        (int, float),
    ):

        log(
            f"Abandono: "
            f"{abandono:.2f}%"
        )

    else:

        log(
            "Abandono: N/D"
        )

    log(
        "Decisão: RECICLAR"
    )

    log(
        "Resultado: "
        f"{nome_rec_resumido(novo_nome)} "
        "criada"
    )

    log(
        f"Duração: "
        f"{duracao:.1f}s"
    )

    log(
        "=============================================="
    )

    log("")


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "ok": True,
        "busy":
            automation_lock.locked(),
    }


# =========================================================
# RECYCLE
# =========================================================

@app.post("/api/recycle")
async def recycle(
    request: Request,
    authorization: str | None = Header(
        default=None
    ),
):

    """
    CONTRATO MANTIDO.

    ENTRADA:

    {
        "campaign_id": "282391"
    }

    SUCESSO:

    true

    ERRO:

    false
    """

    # =====================================================
    # API 1/4 - TOKEN
    # =====================================================

    log(
        "[API 01/04] "
        "Validando autorização..."
    )

    if not token_valido(
        authorization
    ):

        log(
            "[API] Token inválido. "
            "Retornando false."
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )

    log(
        "[API 01/04] OK."
    )


    # =====================================================
    # API 2/4 - BODY
    # =====================================================

    log(
        "[API 02/04] "
        "Lendo body..."
    )

    try:

        body = await request.json()

    except Exception as erro:

        log(
            "[ERRO API] "
            f"Body inválido | "
            f"{type(erro).__name__}: "
            f"{erro}"
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )

    if not isinstance(
        body,
        dict,
    ):

        log(
            "[ERRO API] "
            "Body precisa ser objeto JSON."
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )

    campaign_id = str(
        body.get(
            "campaign_id",
            "",
        )
    ).strip()

    if (
        not campaign_id
        or
        not campaign_id.isdigit()
    ):

        log(
            "[ERRO API] "
            f"campaign_id inválido: "
            f"{campaign_id!r}"
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )

    log(
        "[API 02/04] OK | "
        f"campaign_id={campaign_id}"
    )


    # =====================================================
    # API 3/4 - LOCK
    # =====================================================

    log(
        "[API 03/04] "
        "Verificando lock..."
    )

    if not automation_lock.acquire(
        blocking=False
    ):

        log(
            "[ERRO API] "
            "Já existe reciclagem em execução."
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )

    log(
        "[API 03/04] OK."
    )


    # =====================================================
    # API 4/4 - AUTOMAÇÃO
    # =====================================================

    reset_contexto(
        campaign_id
    )

    try:

        log("")
        log(
            "=============================================="
        )

        log(
            "[API 04/04] "
            "INICIANDO AUTO-RECICLAGEM"
        )

        log(
            f"Campanha: {campaign_id}"
        )

        log(
            "=============================================="
        )


        # =================================================
        # MÉTRICAS PARA O RESUMO
        #
        # Se der erro aqui, NÃO cancela reciclagem.
        # =================================================

        EXECUTION_CONTEXT[
            "metricas"
        ] = consultar_metricas_3c(
            campaign_id
        )

        metricas = EXECUTION_CONTEXT.get(
            "metricas"
        )

        if isinstance(
            metricas,
            dict,
        ):

            EXECUTION_CONTEXT[
                "lista_original"
            ] = metricas.get(
                "nome_original"
            )


        # =================================================
        # EXECUTA SELENIUM
        # =================================================

        resultado = (
            automation
            .executar_reciclagem(
                campaign_id
            )
        )


        # =================================================
        # COMPATIBILIDADE
        #
        # Aceita:
        #
        # True
        #
        # ou:
        #
        # {
        #   "ok": true,
        #   ...
        # }
        # =================================================

        sucesso = (
            resultado is True
            or
            (
                isinstance(
                    resultado,
                    dict,
                )
                and
                resultado.get(
                    "ok"
                ) is True
            )
        )


        # =================================================
        # SUCESSO
        # =================================================

        if sucesso:

            log_resumo_final(
                campaign_id,
                resultado,
            )

            log(
                f"[3C -> N8N] "
                f"Campanha {campaign_id}: "
                "true"
            )

            return JSONResponse(
                content=True,
                status_code=200,
            )


        # =================================================
        # SEM SUCESSO
        # =================================================

        log(
            "[ERRO AUTOMAÇÃO] "
            "A automação terminou "
            "sem indicar sucesso."
        )

        log(
            f"[3C -> N8N] "
            f"Campanha {campaign_id}: "
            "false"
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )


    # =====================================================
    # ERRO
    # =====================================================

    except Exception as erro:

        duracao = (
            time.monotonic()
            -
            EXECUTION_CONTEXT.get(
                "inicio",
                time.monotonic(),
            )
        )

        log("")

        log(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        log(
            "[ERRO FINAL AUTO-RECICLAGEM]"
        )

        log(
            f"Campanha: {campaign_id}"
        )

        log(
            "[PAROU EM] "
            f"{EXECUTION_CONTEXT.get('etapa_atual', 'desconhecida')}"
        )

        log(
            f"Duração até o erro: "
            f"{duracao:.1f}s"
        )

        log(
            f"Erro: "
            f"{type(erro).__name__}: "
            f"{erro}"
        )

        log(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        traceback.print_exc()

        log(
            f"[3C -> N8N] "
            f"Campanha {campaign_id}: "
            "false"
        )

        return JSONResponse(
            content=False,
            status_code=200,
        )


    # =====================================================
    # LIBERA LOCK
    # =====================================================

    finally:

        automation_lock.release()


# =========================================================
# START
# =========================================================

def main():

    host = str(
        os.getenv(
            "HOST",
            "0.0.0.0",
        )
    ).strip() or "0.0.0.0"

    port = int(
        os.getenv(
            "PORT",
            "8080",
        )
    )

    uvicorn.run(
        "src.application.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()