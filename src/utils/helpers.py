from datetime import datetime
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parents[2]
PASTA_SCREENSHOTS = RAIZ_PROJETO / "screenshots"


def log(mensagem):
    print(str(mensagem), flush=True)


def tirar_print_debug(driver, prefixo="erro"):
    PASTA_SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    agora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    caminho = PASTA_SCREENSHOTS / f"{prefixo}_{agora}.png"

    try:
        driver.save_screenshot(str(caminho))
        log(f"[DEBUG] Screenshot salvo em: {caminho}")
        return str(caminho)
    except Exception as erro:
        log(f"[AVISO] Não consegui salvar screenshot: {erro}")
        return None
