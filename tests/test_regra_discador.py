import unittest

from src.service.credtu_automation import (
    _eh_lista_reciclada,
    avaliar_regra_reciclagem_dialer,
    gerar_nome_proxima_reciclagem,
)


class RegraDialerTests(unittest.TestCase):
    def test_exemplo_definitivo_usuario(self):
        casos = [
            # taxa, original, atual, esperado
            (4.0, 100, 100, True),   # Original -> recicla
            (0.4, 100, 90, True),    # REC1 -> recicla
            (2.0, 100, 80, True),    # REC2 -> recicla
            (0.1, 100, 30, False),   # REC3 -> para
        ]

        for taxa, original, atual, esperado in casos:
            resultado = avaliar_regra_reciclagem_dialer(
                taxa,
                original,
                atual,
            )
            self.assertEqual(
                resultado["deve_reciclar"],
                esperado,
            )

    def test_limites_sao_estritos(self):
        # Exatamente 1% ainda recicla.
        self.assertTrue(
            avaliar_regra_reciclagem_dialer(
                1.0,
                100,
                30,
            )["deve_reciclar"]
        )

        # Exatamente 66% ainda recicla.
        self.assertTrue(
            avaliar_regra_reciclagem_dialer(
                0.1,
                100,
                66,
            )["deve_reciclar"]
        )

    def test_original_pode_conter_palavra_rec_no_meio(self):
        self.assertFalse(
            _eh_lista_reciclada(
                "TODOS OS LOTES ALL REC 2508.csv"
            )
        )
        self.assertTrue(
            _eh_lista_reciclada(
                "REC3 - TODOS OS LOTES ALL REC 2508"
            )
        )

    def test_nomes(self):
        self.assertEqual(
            gerar_nome_proxima_reciclagem(
                "TODOS OS LOTES ALL REC 2508.csv"
            ),
            "REC1 - TODOS OS LOTES ALL REC 2508 | AUTO.R",
        )

        self.assertEqual(
            gerar_nome_proxima_reciclagem(
                "REC3 - TODOS OS LOTES ALL REC 2508"
            ),
            "REC4 - TODOS OS LOTES ALL REC 2508 | AUTO.R",
        )


if __name__ == "__main__":
    unittest.main()
