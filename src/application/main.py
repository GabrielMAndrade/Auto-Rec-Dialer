import os
import re
import secrets
import threading
import traceback

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from src.service.credtu_automation import (
    CredtuAutomationError,
    executar_reciclagem,
)


# =========================================================
# ENV
# =========================================================

load_dotenv()


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="Auto Reciclagem 3C - Discador",
    version="4.0.0-dialer",
    description=(
        "Recebe o ID da campanha do n8n e executa "
        "a reciclagem automática do Discador 3C."
    ),
)


# =========================================================
# CONTROLE DE EXECUÇÃO
# =========================================================

# Como a automação utiliza Selenium/Chrome, permitimos
# somente uma execução por vez neste processo.
automation_lock = threading.Lock()


# =========================================================
# LOG
# =========================================================

def log(mensagem):
    print(str(mensagem), flush=True)


# =========================================================
# RESPOSTA PADRÃO DE ERRO
# =========================================================

def resposta_erro(
    status: str,
    stage: str,
    message: str,
    error_type: str | None = None,
    campaign_id: str | None = None,
):
    """
    Mantém HTTP 200 inclusive quando a automação falhar.

    Assim o node HTTP Request do n8n recebe normalmente
    o JSON e pode decidir o próximo passo usando $json.ok.
    """

    body = {
        "ok": False,
        "status": status,
        "stage": stage,
        "message": message,
    }

    if error_type:
        body["error_type"] = error_type

    if campaign_id:
        body["campaign_id"] = campaign_id

    return JSONResponse(
        content=body,
        status_code=200,
    )


# =========================================================
# TOKEN N8N
# =========================================================

def token_valido(
    authorization: str | None,
) -> bool:

    esperado = str(
        os.getenv(
            "DIALER_N8N_API_TOKEN",
            "",
        )
    ).strip()

    if not esperado:
        log(
            "[ERRO API] DIALER_N8N_API_TOKEN não está "
            "configurado no .env."
        )
        return False

    recebido = ""

    if (
        authorization
        and authorization.lower().startswith(
            "bearer "
        )
    ):
        recebido = authorization[7:].strip()

    if not recebido:
        log(
            "[ERRO API] Header Authorization "
            "não contém Bearer Token."
        )
        return False

    return secrets.compare_digest(
        recebido,
        esperado,
    )


# =========================================================
# NORMALIZAÇÃO DO ID DA CAMPANHA
# =========================================================

def normalizar_campaign_id(body: dict):
    """
    Tenta obter o ID da campanha dos nomes mais prováveis
    enviados pelo n8n.

    Campos aceitos:
      1. campaign_id   (preferencial/correto)
      2. campaing_id   (compatibilidade com typo)
      3. idCampanha
      4. id_campanha

    Depois:
      - converte para string;
      - remove espaços;
      - remove qualquer caractere que não seja número;
      - retorna somente os dígitos.

    Exemplos:

        297117
            -> "297117"

        "297117"
            -> "297117"

        " 297117 "
            -> "297117"

        "297 117"
            -> "297117"

        "campanha: 297117"
            -> "297117"
    """

    if not isinstance(body, dict):
        return None, None

    valor_bruto = None
    campo_recebido = None

    for campo in (
        "campaign_id",   # correto
        "campaing_id",   # tolerância ao typo comum do n8n
        "idCampanha",
        "id_campanha",
    ):
        if campo in body:
            valor_bruto = body.get(campo)
            campo_recebido = campo
            break

    if valor_bruto is None:
        return None, None

    # Evita que True vire algo estranho.
    if isinstance(valor_bruto, bool):
        return None, valor_bruto

    # JSON pode entregar um número inteiro diretamente.
    if isinstance(valor_bruto, int):
        if valor_bruto <= 0:
            return None, valor_bruto

        return str(valor_bruto), valor_bruto

    # Caso o n8n envie 297117.0.
    if isinstance(valor_bruto, float):
        if (
            valor_bruto > 0
            and valor_bruto.is_integer()
        ):
            return str(
                int(valor_bruto)
            ), valor_bruto

    texto = str(
        valor_bruto
    ).strip()

    # Remove TUDO que não for dígito.
    somente_numeros = re.sub(
        r"\D",
        "",
        texto,
    )

    # Remove zeros à esquerda somente se houver.
    # Ex.: "000297117" -> "297117"
    somente_numeros = somente_numeros.lstrip("0")

    if not somente_numeros:
        return None, valor_bruto

    try:
        numero = int(
            somente_numeros
        )
    except Exception:
        return None, valor_bruto

    if numero <= 0:
        return None, valor_bruto

    return str(numero), valor_bruto


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():
    return {
        "ok": True,
        "status": "online",
        "app": "auto-recycle-dialer",
        "busy": automation_lock.locked(),
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
    Entrada preferida do n8n:

        {
            "campaign_id": 297117
        }

    Também aceita:

        {
            "idCampanha": 297117
        }

    ou:

        {
            "id_campanha": 297117
        }

    Sucesso:

        {
            "ok": true,
            "status": "success",
            ...
        }

    Erro:

        {
            "ok": false,
            "status": "...",
            "stage": "...",
            "error_type": "...",
            "message": "..."
        }
    """

    # =====================================================
    # 1. TOKEN
    # =====================================================

    if not token_valido(
        authorization
    ):
        log(
            "[ERRO API] Token inválido "
            "ou ausente."
        )

        return resposta_erro(
            status="unauthorized",
            stage="api_auth",
            message=(
                "Token inválido ou ausente."
            ),
        )


    # =====================================================
    # 2. LÊ O BODY
    # =====================================================

    try:
        body = await request.json()

    except Exception as erro:
        log(
            "[ERRO API] Body inválido."
        )
        log(
            f"[DEBUG] Tipo do erro: "
            f"{type(erro).__name__}"
        )
        log(
            f"[DEBUG] Erro: {erro}"
        )

        return resposta_erro(
            status="invalid_json",
            stage="api_request",
            error_type=type(erro).__name__,
            message=(
                "Body inválido. Era esperado "
                "um JSON com o ID da campanha."
            ),
        )


    # =====================================================
    # 3. DEBUG DO BODY RECEBIDO
    # =====================================================

    log("")
    log(
        "=============================================="
    )
    log(
        "[DEBUG API] REQUISIÇÃO RECEBIDA DO N8N"
    )
    log(
        "=============================================="
    )
    log(
        f"[DEBUG API] BODY: {body!r}"
    )

    if isinstance(body, dict):
        log(
            f"[DEBUG API] CHAVES RECEBIDAS: "
            f"{list(body.keys())!r}"
        )
    log(
        f"[DEBUG API] TIPO BODY: "
        f"{type(body).__name__}"
    )


    if not isinstance(
        body,
        dict,
    ):
        return resposta_erro(
            status="invalid_body",
            stage="api_request",
            message=(
                "O body precisa ser "
                "um objeto JSON."
            ),
        )


    # =====================================================
    # 4. NORMALIZA O CAMPAIGN ID
    # =====================================================

    campaign_id, valor_bruto = (
        normalizar_campaign_id(
            body
        )
    )

    log(
        f"[DEBUG API] campaign_id bruto: "
        f"{valor_bruto!r}"
    )

    log(
        f"[DEBUG API] tipo campaign_id bruto: "
        f"{type(valor_bruto).__name__}"
    )

    log(
        f"[DEBUG API] campaign_id normalizado: "
        f"{campaign_id!r}"
    )


    if not campaign_id:
        log(
            "[ERRO API] Não consegui extrair "
            "um ID numérico válido."
        )

        return resposta_erro(
            status="invalid_campaign_id",
            stage="validation",
            message=(
                "Não foi possível extrair um ID "
                "numérico válido do campaign_id. "
                f"Valor recebido: {valor_bruto!r}"
            ),
        )


    # =====================================================
    # 5. CONFIRMA O ID
    # =====================================================

    log(
        f"[OK API] campaign_id aceito: "
        f"{campaign_id}"
    )


    # =====================================================
    # 6. LOCK
    # =====================================================

    if not automation_lock.acquire(
        blocking=False
    ):

        log(
            "[ERRO API] Já existe uma "
            "reciclagem em execução."
        )

        return resposta_erro(
            status="busy",
            stage="queue",
            message=(
                "Já existe uma reciclagem "
                "em execução."
            ),
            campaign_id=campaign_id,
        )


    # =====================================================
    # 7. EXECUTA A AUTOMAÇÃO CREDTU
    # =====================================================

    try:
        log("")
        log(
            "=============================================="
        )

        log(
            f"[N8N -> 3C] "
            f"campaign_id recebido: "
            f"{campaign_id}"
        )

        log(
            "=============================================="
        )


        resultado = executar_reciclagem(
            campaign_id
        )


        log(
            f"[3C -> N8N] "
            f"Campanha {campaign_id}: "
            f"{resultado}"
        )


        return JSONResponse(
            content=resultado,
            status_code=200,
        )


    # =====================================================
    # ERRO ESTRUTURADO DA AUTOMAÇÃO
    # =====================================================

    except CredtuAutomationError as erro:

        log("")
        log(
            "=============================================="
        )

        log(
            "[ERRO AUTOMAÇÃO]"
        )

        log(
            f"campaign_id = "
            f"{campaign_id}"
        )

        log(
            f"status = "
            f"{erro.status}"
        )

        log(
            f"stage = "
            f"{erro.stage}"
        )

        log(
            f"error_type = "
            f"{erro.error_type}"
        )

        log(
            f"message = "
            f"{erro.message}"
        )

        log(
            "=============================================="
        )


        traceback.print_exc()


        body_erro = erro.to_dict()

        body_erro[
            "campaign_id"
        ] = campaign_id


        log(
            f"[3C -> N8N] "
            f"{body_erro}"
        )


        return JSONResponse(
            content=body_erro,
            status_code=200,
        )


    # =====================================================
    # ERRO INESPERADO
    # =====================================================

    except Exception as erro:

        log("")
        log(
            "[ERRO INESPERADO API] "
            f"{type(erro).__name__}: "
            f"{erro}"
        )

        traceback.print_exc()


        return resposta_erro(
            status="unexpected_error",
            stage="api_execution",
            error_type=type(erro).__name__,
            message=(
                str(erro)
                or type(erro).__name__
            ),
            campaign_id=campaign_id,
        )


    # =====================================================
    # LIBERA A API PARA A PRÓXIMA EXECUÇÃO
    # =====================================================

    finally:
        automation_lock.release()


# =========================================================
# EXECUÇÃO DIRETA COM UVICORN
# =========================================================

def main():

    host = str(
        os.getenv(
            "DIALER_HOST",
            "0.0.0.0",
        )
    ).strip() or "0.0.0.0"


    port = int(
        os.getenv(
            "DIALER_PORT",
            "6777",
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