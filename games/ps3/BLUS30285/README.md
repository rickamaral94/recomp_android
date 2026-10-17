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

## Análise do log do Armadasx3 (2026-10-17)

Fonte: pacote de diagnóstico do usuário `armadasx3-diagnostico-20261017-125326-BLUS30285.zip`
(ARMSX3 `v0.0.43-21645-44cf6141`), três boots deste jogo em `ARMSX3.log` e `ARMSX3.old.log`.
Extraído com `tools/ps3/parse_rpcs3_log.py` → `analysis/armadasx3-log-20261017.json`.
Cruzado com o ps3recomp `39a36296` por `tools/ps3/hle_coverage.py` →
`analysis/hle-coverage-ps3recomp-39a36296.json`.

### Fatos (impressos pelo emulador)

| Fato | Evidência |
|---|---|
| Hash PPU `PPU-9cd5730cfe6d47774b8e4a45dae1fb32c2cb46fb`, igual nos 3 boots | `ARMSX3.log:534` |
| SDK `0x250001`, SELF authid `0x1010000001000003`; código em `0x10000` (17,7 MB), dados em `0x10f0000` | `ARMSX3.log:491-503, 1412` |
| ISO sem criptografia ("enc type: NONE") | `ARMSX3.log`, "ISO: init" |
| **408 funções importadas em 26 módulos**; 14 NIDs sem nome no RPCS3 (todos em `libad_core`/`libad_async`) | `ARMSX3.log:1418+` |
| Única biblioteca de firmware carregada em LLE: `liblv2.sprx` | `ARMSX3.log:2197` |
| **15 imagens SPU** embutidas no executável | linhas `SPU executable hash` |
| Threads PPU: `main_thread`, `LoopSimulation`, `LoopRender`, `MoviePlayer2 Decode Thread`, `FileCopier::Thread` (instalação no HDD), threads de save | prefixos de thread do log |
| Threads SPU: grupo de 6 "Job Manager - Job Thread", criado por `sys_spu_thread_group_create`/`sys_spu_thread_initialize` (6 de cada) | estatísticas de syscalls |
| Em ~37 min: `sys_ppu_thread_yield` 811 milhões, `sys_mutex_lock/unlock` ~24 milhões cada, `sys_semaphore_create/destroy` ~4 milhões cada | último bloco "PPU Syscall Usage Stats" de `ARMSX3.old.log` |
| Chamadas ainda TODO no emulador: `_sys_prx_register_module`, `sys_net_infoctl`, `cellNetCtlAddHandler`, `cellAudioOutGetDeviceInfo` | linhas "TODO:" |
| Arquivos ausentes tratados pelo jogo (CELL_ENOENT): dados opcionais em `/dev_hdd0/game/BLUS30285/…` e índices `indexedassets.txt` | erros de `sys_fs` |

### Cobertura no ps3recomp (critério: nome no código-fonte, não correção)

| | Definido | Só mencionado | Ausente |
|---|---|---|---|
| 408 imports | 296 | 34 | 78 |
| 77 syscalls vistas | 51 | 11 | 15 |

Os ausentes se concentram em:
- **Rede e PSN:** `sceNp` (12), `sceNpCommerce2` (11), `sys_net` (3) e `cellHttp` (2).
- **`libad_core`/`libad_async` (21):** são as funções `sceAd*`.
- **`cellCelpEnc` (8):** codificação de voz.
- **`sysPrxForUser` (11):** entre elas `sys_raw_spu_load` e `sys_prx_register_library`.
- **Funções isoladas:** `cellSaveDataListAutoSave`, `cellSaveDataFixedDelete`, `cellGameDataExitBroken`, `cellKbRead`, `cellGcmGetLastSecondVTime` e `cellSpursGetSpuThreadId`.

### Inferências (a confirmar na análise estática)

- `sceAd*` parece ser a biblioteca de publicidade in-game da PSN. Junto com PSN, comércio,
  rede, voz e câmera, pode responder "sem rede / sem dispositivo" num port offline. São stubs
  **declarados**, não silenciosos. Confiança: média, pelos nomes.
- As syscalls ausentes `_sys_ppu_thread_create`, `_sys_lwmutex_*` e `_sys_prx_*` provavelmente
  vêm do `liblv2.sprx` em LLE dentro do emulador. No ps3recomp, o `sysPrxForUser` em HLE ocupa
  esse lugar. Só a busca por instruções `sc` no ELF mostra quais syscalls o jogo faz direto.
  Confiança: média.
- O "Job Manager" é um grupo de 6 threads SPU próprio (syscalls `sys_spu_thread_*`), não um
  workload do SPURS. O jogo também importa `cellSpurs`, provavelmente para outra coisa (áudio?).
  Para o port, os programas do Job Manager e o laço quente (LS `0x3fd00`) são o primeiro alvo
  de lift de SPU. Confiança: média.
- O `sys_ppu_thread_yield` em massa (~365 mil/s) é espera ocupada. Num port nativo vira
  `sched_yield`/espera real, e é aí que pode haver ganho sobre o emulador. Confiança: baixa,
  até medir.

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
2. ~~Pacote de diagnóstico do Armadasx3~~: feito (seção acima).
3. Para a análise estática, o executável em claro (ELF) da sua cópia. O envio a este ambiente
   foi autorizado em 2026-10-17. O projeto não descriptografa nada. Caminho conhecido: o RPCS3 de
   desktop, em *Utilities › Decrypt PS3 Binaries*, aplicado ao `PS3_GAME/USRDIR/EBOOT.BIN` da
   ISO, gera `EBOOT.elf`. O hash dele vai para `elf_sha256` no `profile.toml`.

## Regras deste perfil

- Correções deste jogo ficam neste diretório ou atrás do ID dele; nada global sem prova de que é
  seguro para outros títulos.
- Código gerado a partir do jogo nunca entra no repositório (`.gitignore`: `games/**/private/`).
