# Fight Night Round 4 — BLUS30285 (PS3, EUA)

Perfil do port. Estado: **none**. O dump foi identificado (inventário abaixo), mas nenhuma
análise ou recompilação foi feita.

## Build aceito

Do inventário do usuário (`inventory/disc-01.00.json`, gerado no Odin 2 Portal em 2026-10-17):

| Campo | Valor |
|---|---|
| PARAM.SFO | TITLE_ID `BLUS30285`, APP_VER `01.00`, VERSION `01.00`, CATEGORY `DG` (disco), PS3_SYSTEM_VER `02.7600` |
| ISO | 4.755.423.232 bytes, SHA-256 `878e75f1…5fb00c` |
| EBOOT.BIN | 18.743.896 bytes, **SELF** (magic `SCE`), SHA-256 `e49c8099…8284b3` |

A ISO é legível como ISO 9660 em claro (o PARAM.SFO e o EBOOT foram lidos direto). O EBOOT é
o SELF assinado do disco: a análise estática precisa do ELF que o usuário extrair dele.
Sem atualização instalada: o port é para a versão 01.00.

## O que já se sabe (com fonte)

Nenhum dos fatos abaixo vem dos arquivos do jogo. São medições do mesmo jogo rodando **emulado**
no mesmo aparelho, feitas no Armadasx3 (`rickamaral94/Armadasx3`, commit `79102d68`).

| Fato | Fonte |
|---|---|
| No Odin 2 Portal o jogo é "jogável com problemas": 48–51 FPS de média, p50 ~18 ms, p99 35–41 ms, travadas de até ~1,8 s | `docs/armadasx3/COMPATIBILIDADE.md`, linhas 39–46 (2026-10-14 a 16) |
| O gargalo é a **CPU**: seis threads de SPU a ~80% cada, PPU 85–90%, RSX 65–80%; a GPU fica folgada | `docs/armadasx3/OTIMIZACAO.md` |
| O jogo usa seis threads SPU do "Job Manager"; com Accurate SPU Reservations ligado, ~53 mil barreiras/s em `vm::writer_lock` | `ConfigDatabase.kt` (comentário de BLUS30285) |
| 45% do tempo de SPU fica num laço de busca de mínimo (LS `0x3fd00`) com comparação u64 sem sinal | `rpcs3/Emu/Cell/SPULLVMRecompiler.cpp` ~8088 |
| A PPU faz ~690 mil `sys_ppu_thread_yield`/s (espera ocupada) | `docs/armadasx3/UPSTREAM.md` |
| Chama `sys_rsx_context_attribute(0x101)` e `sys_rsx_attribute(0x2/0x202)` a cada quadro | `rpcs3/Emu/Cell/lv2/sys_rsx.cpp` |
| Banco de compatibilidade do RPCS3: "Ingame", último teste em 2018-11-18 | API `rpcs3.net/compatibility`, consultada em 2026-10-17 |

**Inferência, ainda não verificada:** o "Job Manager" e os nomes de thread sugerem um sistema de
jobs próprio da EA rodando nas SPUs. Se for o caso, cada programa de SPU precisa ser extraído e
recompilado (como os 7 programas do gow2-recomp). Só a análise do executável confirma.

## Implicação para o port

A recompilação só vale a pena se superar a linha de base emulada (~50 FPS, p99 ~35 ms no mesmo
aparelho). Como o limite é a CPU (SPU + sincronização), o ganho possível está em:

- tirar o custo de emulação das reservas e do DMA das SPUs;
- trocar a espera ocupada da PPU por espera real;
- compilar o laço quente da SPU direto para NEON.

Nada disso está garantido: o gow2-recomp, por exemplo, ficou limitado pela thread principal no
Android.

## Próximos passos (precisam do usuário)

1. ~~Inventário do dump~~ — feito (`inventory/disc-01.00.json`).
2. Mandar um pacote de diagnóstico do Armadasx3 de uma sessão desse jogo (por exemplo o 101112).
   O log traz o hash PPU, os módulos PRX carregados, as funções HLE chamadas e as threads SPU.
   É a primeira lista de imports e subsistemas, sem tocar no binário.
3. Para a análise estática (M2 deste jogo), o executável em claro (ELF) da sua cópia. O projeto
   não descriptografa nada.

## Regras deste perfil

- Correções deste jogo ficam neste diretório ou atrás do ID dele; nada global sem prova de que é
  seguro para outros títulos.
- Código gerado a partir do jogo nunca entra no repositório (`.gitignore`: `games/**/private/`).
