#!/usr/bin/env python3
"""Atualiza o arquivo site/dados.json com as pontuações da liga no Cartola FC.

O que este script faz
---------------------
1. Descobre a rodada atual do Cartola.
2. Para cada time da liga, busca a pontuação de cada rodada já encerrada,
   descontando o bônus do capitão (o capitão conta 1x, e não 1,5x).
3. Salva tudo em site/dados.json. A página (site/index.html) lê esse arquivo e
   monta as tabelas de cada turno e a classificação geral.

Rodadas encerradas não mudam mais, então ficam guardadas no próprio dados.json
e não são buscadas de novo. A exceção são as últimas RODADAS_A_REVALIDAR, que são
conferidas a cada execução caso o Cartola corrija alguma súmula depois da rodada.

Uso:
    python atualizar.py                  # atualiza site/dados.json
    python atualizar.py --refazer-tudo   # ignora o que já está salvo e busca tudo de novo
    python atualizar.py --saida x.json   # grava em outro arquivo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cartolafc

# ---------------------------------------------------------------------------
# Configuração da liga: é aqui que você mexe se algo mudar
# ---------------------------------------------------------------------------
IDS_TIMES = [
    29674391,
    14156535,
    12039729,
    25577506,
    25330326,
    49127596,
    8812795,
    24326206,
]
TOTAL_RODADAS = 38     # rodadas do campeonato
RODADAS_POR_TURNO = 7  # 38 // 7 = 5 turnos (as rodadas 36 a 38 ficam fora dos turnos)

# ---------------------------------------------------------------------------
# Ajustes técnicos
# ---------------------------------------------------------------------------
RODADAS_A_REVALIDAR = 2     # busca de novo as últimas N rodadas encerradas a cada execução
TENTATIVAS = 5              # tentativas por chamada à API antes de desistir
ESPERA_INICIAL = 2.0        # segundos até a 2ª tentativa (dobra a cada nova falha)
PAUSA_ENTRE_CHAMADAS = 0.3  # segundos entre chamadas, para não sobrecarregar a API
VERSAO_FORMATO = 1          # versão do formato do dados.json (a página confere)

ARQUIVO_PADRAO = Path(__file__).resolve().parent / "site" / "dados.json"


class ErroApi(Exception):
    """A API do Cartola não respondeu depois de todas as tentativas."""


def com_tentativas(descricao, funcao):
    """Executa `funcao()` e tenta de novo, com espera crescente, se der erro."""
    ultimo_erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return funcao()
        except Exception as erro:  # a biblioteca pode levantar vários tipos de erro
            ultimo_erro = erro
            if tentativa < TENTATIVAS:
                espera = ESPERA_INICIAL * 2 ** (tentativa - 1)
                print(
                    f"  falhou ({descricao}): {erro!r}. "
                    f"Nova tentativa em {espera:.0f}s ({tentativa}/{TENTATIVAS})",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(espera)
    raise ErroApi(f"não consegui {descricao} depois de {TENTATIVAS} tentativas: {ultimo_erro!r}")


def monta_turnos():
    quantidade = max(TOTAL_RODADAS // RODADAS_POR_TURNO, 1)
    turnos = []
    for i in range(quantidade):
        ultimo = i == quantidade - 1
        turnos.append(
            {
                "numero": i + 1,
                "inicio": i * RODADAS_POR_TURNO + 1,
                "fim": TOTAL_RODADAS if ultimo else (i + 1) * RODADAS_POR_TURNO,
            }
        )
    return turnos


def pontuacao_sem_bonus_capitao(time_cartola):
    """Pontuação do time na rodada, sem o bônus do capitão (mesma regra do app antigo)."""
    pontos = float(time_cartola.ultima_pontuacao or 0)
    for atleta in time_cartola.atletas or []:
        if atleta.is_capitao is True:
            pontos -= float(atleta.pontos or 0) * 0.5
    return round(pontos, 4)


def extrai_info(time_cartola, id_time):
    """Nome do time para exibir na página."""
    info = time_cartola.info
    slug = getattr(info, "slug", None) or str(id_time)
    return {
        "id": id_time,
        "slug": slug,
        "nome": getattr(info, "nome", None) or slug,
        "nome_cartola": getattr(info, "nome_cartola", None) or "",
    }


def info_basica(api, id_time, rodada):
    """Plano B para saber o nome de um time quando não há nenhuma rodada para buscar."""
    try:
        return extrai_info(api.time(id_time, rodada), id_time)
    except Exception:
        return {"id": id_time, "slug": str(id_time), "nome": str(id_time), "nome_cartola": ""}


def carrega_existente(caminho):
    """Lê o dados.json atual (se existir e estiver no formato esperado)."""
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Aviso: o dados.json atual está ilegível. Vou refazer do zero.", file=sys.stderr)
        return {}
    if not isinstance(dados, dict) or dados.get("versao") != VERSAO_FORMATO:
        return {}
    if not isinstance(dados.get("rodadas"), dict):
        dados["rodadas"] = {}
    if not isinstance(dados.get("times"), list):
        dados["times"] = []
    return dados


def coleta(api, existente, refazer_tudo):
    """Busca o que falta na API e devolve o conteúdo novo do dados.json."""
    rodada_atual = int(com_tentativas("consultar a rodada atual", lambda: api.mercado().rodada_atual))
    turnos = monta_turnos()
    ultima_rodada_dos_turnos = turnos[-1]["fim"] if turnos else 0

    # Só contam rodadas já encerradas (menores que a rodada atual) e que pertencem a algum turno.
    ultima_encerrada = min(rodada_atual - 1, ultima_rodada_dos_turnos)
    encerradas = list(range(1, ultima_encerrada + 1))
    revalidar = set(encerradas[-RODADAS_A_REVALIDAR:]) if RODADAS_A_REVALIDAR > 0 else set()
    print(
        f"Rodada atual: {rodada_atual}. "
        f"Rodadas encerradas consideradas: {'nenhuma' if not encerradas else f'1 a {ultima_encerrada}'}.",
        flush=True,
    )

    cache = {}
    if refazer_tudo:
        print("Modo --refazer-tudo: ignorando o que já estava salvo.", flush=True)
    else:
        salva = existente.get("rodada_atual")
        if isinstance(salva, int) and rodada_atual < salva:
            print("A rodada atual é menor que a salva (nova temporada?). Descartando o que estava salvo.", flush=True)
        else:
            cache = existente.get("rodadas", {})

    infos = {t["id"]: t for t in existente.get("times", []) if isinstance(t, dict) and "id" in t}
    rodadas = {}
    buscas = 0

    for id_time in IDS_TIMES:
        antigas = cache.get(str(id_time), {})
        do_time = {}
        for rodada in encerradas:
            chave = str(rodada)
            if chave in antigas and rodada not in revalidar:
                do_time[chave] = antigas[chave]
                continue
            if buscas:
                time.sleep(PAUSA_ENTRE_CHAMADAS)
            time_cartola = com_tentativas(
                f"buscar o time {id_time} na rodada {rodada}",
                lambda i=id_time, r=rodada: api.time(i, r),
            )
            buscas += 1
            do_time[chave] = pontuacao_sem_bonus_capitao(time_cartola)
            infos[id_time] = extrai_info(time_cartola, id_time)
            print(f"  time {id_time}, rodada {rodada}: {do_time[chave]}", flush=True)
        rodadas[str(id_time)] = do_time

        if id_time not in infos:
            infos[id_time] = info_basica(api, id_time, rodada_atual)

    print(f"Buscas feitas na API: {buscas}.", flush=True)
    return {
        "versao": VERSAO_FORMATO,
        "rodada_atual": rodada_atual,
        "config": {"total_rodadas": TOTAL_RODADAS, "rodadas_por_turno": RODADAS_POR_TURNO},
        "turnos": turnos,
        "times": [infos[i] for i in IDS_TIMES],
        "rodadas": rodadas,
    }


def grava(caminho, conteudo):
    """Grava o JSON de forma segura (arquivo temporário e troca no final)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    final = {"versao": conteudo["versao"], "gerado_em": agora}
    final.update({k: v for k, v in conteudo.items() if k != "versao"})
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(caminho)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Atualiza o dados.json com as pontuações do Cartola.")
    parser.add_argument("--saida", type=Path, default=ARQUIVO_PADRAO, help="arquivo de saída (padrão: site/dados.json)")
    parser.add_argument("--refazer-tudo", action="store_true", help="ignora o que já está salvo e busca todas as rodadas de novo")
    args = parser.parse_args(argv)

    existente = carrega_existente(args.saida)
    try:
        conteudo = coleta(cartolafc.Api(), existente, args.refazer_tudo)
    except ErroApi as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        print("O dados.json não foi alterado.", file=sys.stderr)
        return 1

    # Se nada mudou, não mexe no arquivo (assim não há commit à toa nem data de atualização falsa).
    anterior = {k: v for k, v in existente.items() if k != "gerado_em"}
    if anterior == conteudo:
        print("Sem mudanças nos dados. Nada a gravar.")
        return 0

    grava(args.saida, conteudo)
    print(f"Dados gravados em {args.saida}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
