# Credtu Auto Reciclagem — n8n ↔ 3C

## Contrato da integração

### n8n -> 3C

O n8n envia **somente o ID da campanha**.

No seu workflow, o valor vem de:

```javascript
{{ $('Infos. Campanha').item.json.idCampanha }}
```

Node HTTP Request:

```text
Method: POST
URL: http://IP_DA_VPS:8080/api/recycle
```

Header:

```text
Authorization: Bearer <N8N_API_TOKEN_DO_ENV>
Content-Type: application/json
```

Body JSON:

```json
{
  "campaign_id": "{{ $('Infos. Campanha').item.json.idCampanha }}"
}
```

Não envie nome da lista, ID da lista, taxa de abandono ou qualquer
outro dado para a automação Credtu.

---

## 3C -> n8n

A resposta do endpoint `/api/recycle` é literalmente:

```json
true
```

quando TODA a automação terminou com sucesso.

Ou:

```json
false
```

se qualquer etapa der erro.

O endpoint usa HTTP 200 nos dois casos para o n8n conseguir receber
o boolean e decidir o próximo passo sem transformar a resposta `false`
em erro técnico do node HTTP Request.

Detalhes de erro ficam apenas no log da VPS.

---

## Fluxo executado internamente

```text
campaign_id recebido
-> abre Chrome
-> login Credtu
-> abre campanha
-> aba URA
-> abre todas as listas
-> pega última lista
-> abre opções
-> Reciclar
-> fecha popup de exclusão se aparecer
-> lê nome atual
-> REC + 1
-> adiciona | AUTO.R
-> marca as 4 boxes
-> preenche novo nome
-> confirma reciclagem
-> espera 5 segundos
-> fecha Chrome
-> true
```

Se qualquer etapa falhar:

```text
erro
-> salva screenshot local
-> fecha Chrome
-> false
```

---

## Exemplo para IF no n8n

Depois do HTTP Request da automação 3C, use o valor booleano retornado
para separar sucesso e erro.

A API não devolve mensagem, nome de lista, campaign_id ou detalhe de erro.
Somente `true` ou `false`.
