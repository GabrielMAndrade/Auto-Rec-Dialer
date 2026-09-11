# Auto-Recycle Discador — 3C + n8n

Aplicação independente da Auto-Recycle URA.

## Ambiente

- URL 3C: configurada por `DIALER_BASE_URL`
- API local/VPS: porta `6777`
- Serviço systemd: `credtu-dialer.service`
- Pasta sugerida na VPS: `/home/node/Auto-Recycle-Dialer`

A aplicação **não acessa a aba URA**. Depois de abrir a campanha, permanece em
**Listas** e utiliza o botão já conhecido para expandir todas as listas.

## Regra definitiva de reciclagem

A automação só **PARA** quando as duas condições forem verdadeiras ao mesmo tempo:

```python
pode_parar = (
    taxa_abandono < 1.0
    and
    (tamanho_lista_atual / tamanho_lista_original) < 0.66
)

deve_reciclar = not pode_parar
```

Portanto, continua reciclando se pelo menos uma destas situações ainda existir:

- taxa de abandono >= 1%; ou
- lista atual ainda possui >= 66% da quantidade da lista original.

Os operadores são estritos: **1,0%** e **66% exatos ainda reciclam**.

### Exemplo

Original = 100 clientes.

| Lista | Abandono | Clientes | % da original | Decisão |
|---|---:|---:|---:|---|
| Original | 4,0% | 100 | 100% | RECICLA |
| REC1 | 0,4% | 90 | 90% | RECICLA |
| REC2 | 2,0% | 80 | 80% | RECICLA |
| REC3 | 0,1% | 30 | 30% | NÃO RECICLA |

## Como a lista original é encontrada

Não usamos `tr[60]`, `tr[63]` ou qualquer linha fixa.

A automação começa pela **última linha da tabela**, que é a lista atual.

- se a lista atual não começa com `REC<n>`, ela própria é a lista original;
- se começa com `REC<n>`, a automação sobe pelas RECs consecutivas;
- a primeira linha anterior que não começa com `REC<n>` é tratada como a original daquele bloco;
- o nome-base da REC atual é comparado com o nome-base da original para evitar atravessar silenciosamente para outro bloco.

A quantidade de clientes é sempre lida em `td[3]` **da linha encontrada dinamicamente**.

## Colunas usadas

O layout atual usa:

```text
td[2] -> nome
td[3] -> quantidade de clientes
td[6] -> taxa de abandono
td[7] -> data de finalização
```

As colunas são configuráveis no `.env`, então uma alteração futura da interface
não exige reescrever a regra.

O botão de visualizar todas as listas permanece no XPath:

```text
/html/body/div[1]/div[2]/div[1]/div[2]/div/div[2]/div/div/div[2]/button
```

## Nome da próxima REC

```text
TODOS OS LOTES ALL REC 2508.csv
-> REC1 - TODOS OS LOTES ALL REC 2508 | AUTO.R

REC3 - TODOS OS LOTES ALL REC 2508
-> REC4 - TODOS OS LOTES ALL REC 2508
```

## Opções de reciclagem do Discador

São processados os checkboxes:

```text
1, 2, 4, 5 e 6
```

## 2FA

A autenticação TOTP usa `pyotp` e a variável:

```text
DIALER_TOTP_SECRET
```

A secret real está apenas no `.env` preparado para a VPS. O `.env` está no
`.gitignore` e **não deve ser commitado**.

## Preparação

Preencha no `.env`:

```text
DIALER_EMAIL=
DIALER_PASSWORD=
DIALER_N8N_API_TOKEN=
```

A URL, porta e parâmetros da regra já estão preparados.

## Instalação na VPS

Copie a pasta para:

```bash
/home/node/Auto-Recycle-Dialer
```

Depois:

```bash
cd /home/node/Auto-Recycle-Dialer
chmod +x start.sh deploy/setup_vps.sh
./deploy/setup_vps.sh
```

Valide:

```bash
curl http://127.0.0.1:6777/health
```

Resultado esperado:

```json
{
  "ok": true,
  "status": "online",
  "app": "auto-recycle-dialer",
  "busy": false
}
```

## n8n

Endpoint:

```text
POST http://IP_DA_VPS:6777/api/recycle
```

Header:

```text
Authorization: Bearer <DIALER_N8N_API_TOKEN>
Content-Type: application/json
```

Body:

```json
{
  "campaign_id": "286663"
}
```

Quando a regra manda parar, a resposta é sucesso operacional, mas sem reciclagem:

```json
{
  "ok": true,
  "status": "recycle_not_needed",
  "recycled": false,
  "deve_reciclar": false
}
```

Quando recicla:

```json
{
  "ok": true,
  "status": "success",
  "recycled": true
}
```

Erros continuam retornando `status`, `stage`, `error_type`, `message` e os campos
de diagnóstico detalhado já existentes na automação.

## Teste da regra sem abrir o Chrome

```bash
.venv/bin/python -m unittest tests/test_regra_discador.py -v
```
