# AT NIGHT'S LEAGUE - Turnos

Classificação por turnos da liga no Cartola FC, publicada como um site estático no GitHub Pages.

## Como funciona

1. Um workflow do GitHub Actions (`.github/workflows/atualizar.yml`) roda de hora em hora.
2. Ele executa `atualizar.py`, que busca na API do Cartola a pontuação de cada time em cada rodada já encerrada, sem o bônus do capitão, e grava o resultado em `site/dados.json`.
3. Se o arquivo mudou, o workflow faz o commit e publica a pasta `site/` no GitHub Pages.
4. A página `site/index.html` lê o `dados.json` e monta a classificação geral e a de cada turno.

Rodadas encerradas não mudam mais, então ficam guardadas no `dados.json` e não são buscadas de novo. Só as 2 últimas encerradas são conferidas a cada execução, caso o Cartola corrija alguma súmula.

## Arquivos

| Arquivo | Para que serve |
| --- | --- |
| `atualizar.py` | Busca os dados no Cartola e gera o `site/dados.json` |
| `site/index.html` | A página (HTML, CSS e JavaScript em um arquivo só) |
| `site/dados.json` | Pontuações por time e rodada. Gerado pelo workflow, não precisa editar |
| `.github/workflows/atualizar.yml` | Agendamento, commit dos dados e publicação |

## Configuração inicial (uma vez só)

1. No repositório, vá em **Settings → Pages** e, em **Source**, escolha **GitHub Actions**.
2. Vá na aba **Actions**, abra **Atualizar dados e publicar o site** e clique em **Run workflow**. A primeira execução busca todas as rodadas e leva alguns minutos.
3. O endereço do site aparece no fim da execução e em **Settings → Pages**.

Para atualizar na hora, use o **Run workflow** de novo. Marque **refazer_tudo** se quiser buscar todas as rodadas do zero.

## Ajustes

No topo do `atualizar.py`:

- `IDS_TIMES`: ids dos times da liga.
- `TOTAL_RODADAS` e `RODADAS_POR_TURNO`: com 38 rodadas e turnos de 7, são 5 turnos e as rodadas 36 a 38 não entram em nenhum deles.
- `RODADAS_A_REVALIDAR`: quantas rodadas encerradas são conferidas de novo a cada execução.

No topo do script de `site/index.html`:

- `CAMPO_NOME`: o que aparece na coluna Time (`"slug"`, `"nome"` ou `"nome_cartola"`).

Para mudar a frequência, edite a linha `cron` do workflow. O horário é sempre UTC (Brasília é UTC-3).

## Regras de contagem

- Só contam rodadas já encerradas, ou seja, menores que a rodada atual do Cartola.
- O bônus do capitão é descontado: o capitão conta 1x, e não 1,5x.
- Na tabela do turno em andamento, `P/rodada` é a diferença para o líder dividida pelas rodadas que restam.

## Testar no computador

```bash
pip install -r requirements.txt
python atualizar.py              # gera site/dados.json
python -m http.server -d site    # abre em http://localhost:8000
```
