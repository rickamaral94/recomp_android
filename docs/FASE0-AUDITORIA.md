# Fase 0 — Auditoria e viabilidade (recomp_android)

Data: 2026-10-17. Alvo: AYN Odin 2 Portal (Snapdragon 8 Gen 2, Adreno 740, Android ARM64, Vulkan).

Este documento é só análise. **Nenhum código foi escrito, compilado ou executado em aparelho.**
Tudo o que está marcado como "observado" foi lido nos repositórios nos commits indicados; o que é
"inferência" ou "não verificado" está marcado assim.

---

## 1. Estado dos repositórios do usuário

| Repositório | Commit inspecionado | Licença | Estado observado |
|---|---|---|---|
| `rickamaral94/recomp_android` | — | — | **Vazio**: nenhum commit, nenhuma ref (clone em 2026-10-17 retornou "empty repository"). |
| `rickamaral94/Armadasx3` | `79102d689ef910b91081cd4693783aabfc9094ca` (2026-10-17, branch `ccr-5c324462-syx7vr`, único branch remoto) | GPL-2.0-only | Fork do ARMSX3 → RPCS3. É um **emulador** PS3 (JIT/LLVM), não um recompilador estático. Não tem nada de PS2. |

### Armadasx3 — o que existe e serve de referência

Fonte: `ARMADASX3.md`, `docs/armadasx3/AUDITORIA.md`, `DIAGNOSTICO.md`, árvore `android/`.

- PPU/SPU via LLVM gerando AArch64 em tempo de execução; RSX com backend Vulkan adaptado a
  Adreno/Turnip (+16 mil linhas no ARMSX3); drivers via libadrenotools.
- Build Android: NDK `29.0.14206865`, CMake 3.30.5, JDK 17, só `arm64-v8a`, variante `a13`
  (armv8.2-a+dotprod+fp16) indicada para o 8 Gen 2. O core (`libarmsx3-core.so`, ~1,3 GB sem strip)
  compila no GitHub Actions em ~67 min (execução 38052040154, commit `217363f5`, segundo o próprio
  `ARMADASX3.md` — não reexecutei).
- Diagnóstico: ZIP com `report.json` (`schema = "armadasx3.diagnostic-report"`,
  `schema_version = 1`), código Kotlin em `com.armadasx3.*` (`DiagnosticReport.kt`,
  `FrameStats.kt`, `MetricsSampler.kt`, `PathRedactor.kt`, …). **Não validado em aparelho**
  (Marco 4 do próprio projeto). Baseline no Odin 2 Portal: não iniciado (Marco 5).
- Testes: JVM do app; testes gtest do RPCS3 são de desktop; existe `armadasx3_spu_difftest.cpp`.

**Papel no recomp_android:** oráculo de comportamento PS3 (rodar o mesmo homebrew no emulador e
comparar saídas) e fonte do *formato* de diagnóstico. **Não** copiar código dele para o
recomp_android sem resolver a licença (ver §4).

---

## 2. Ferramentas e projetos de referência

| Projeto | Commit | Data | Licença | Atividade |
|---|---|---|---|---|
| `morluto/rea` (REA) | `3fa972af7c7cb6cf014ffc426bdf7130dc6f2fd2` (pacote `rea-agents` 6.5.0) | 2026-10-18 | MIT | Muito ativo |
| `sp00nznet/ps3recomp` | `39a36296511c445707adabcd312f0b740cfbd694` | 2026-10-16 | MIT | Ativo, CI em Windows/macOS/Linux(+Vulkan lavapipe) |
| `andrebrumdev/gow2-recomp` | `a787912c7b2e2f61bb387c9c22722a93e6c5ee3c` | 2026-10-04 | MIT (só código original; ver `NOTICE.md`) | Ativo |
| `ran-j/PS2Recomp` | `eb8688b2fd191129f103a39543002c005b33409c` | 2026-10-14 | **GPL-3.0** | Ativo |
| `BlackLineInteractive/PS2Recomp-Studio` | `423c4b76f01042e77505dd4b44f2909c44d49de7` | 2026-08-06 | **GPL-3.0** | Fork do PS2Recomp, parado há ~2,5 meses; 136 arquivos diferem do upstream |

### 2.1 REA

Observado no `README.md`:

- É um servidor **MCP** + CLI (Node ≥ 22.19; o container tem 22.22.0). Não analisa binários sozinho
  em profundidade: a análise nativa usa **Ghidra, IDA ou Hopper** já instalados; offline também
  aceita GNU objdump e Rizin fornecidos pelo usuário.
- O código cita MIPS (incl. metadados de ELF MIPS) e PowerPC, mas o README **não** lista PS2/PS3
  como alvos. Suporte a R5900 (MMI) e a SPU **depende do provedor**: o Ghidra base tem PowerPC 64
  BE e MIPS; R5900 exige uma extensão de terceiros e SPU exige um módulo de processador de
  terceiros. **Nada disso foi verificado aqui** (Ghidra não está instalado no container).
- **Ponto crítico de privacidade (observado):** "REA analyzes targets locally. Your agent receives
  the tool results." Ou seja, pseudocódigo/assembly volta para o agente — e o agente é um LLM
  remoto. Isso conflita com a regra "não enviar binários do jogo ou dados derivados a serviços
  externos". Consequência:
  - Neste ambiente em nuvem, REA só será usado com **homebrew e binários sintéticos**.
  - Para jogos comerciais, REA tem de rodar na máquina do usuário com um agente/modelo local, ou o
    usuário decide explicitamente aceitar o envio. A decisão é do usuário (ver §7).
- REA não substitui lifter, loader, runtime nem backend gráfico.

### 2.2 ps3recomp (PS3)

- Pipeline em Python: `elf_parser.py`, `ppu_disasm.py`, `ppu_lifter.py`, `spu_disasm.py`,
  `spu_lifter.py`, `prx_analyzer.py`, `nid_database.py`, integração Ghidra/IDA
  (`tools/ghidra_analyze.py`, `tools/ida_analyze.py`). Runtime em C/C++: contexto PPU/SPU, MFC/DMA,
  LV2 syscalls, ~100 módulos HLE (cellGcm, cellSpurs, cellAudio, cellPad…).
- **Plataforma (observado no README):** só Windows/D3D12 roda um jogo recompilado "nesta árvore".
  Linux/macOS compilam, mas o *boot scaffold* PPU nunca levou um título ao gameplay ali.
  **Não há Android na árvore.**
- **Inconsistência a resolver:** o README diz que Vulkan roda os shaders do título em CI (lavapipe);
  `docs/MODULE_STATUS.md` diz "Vulkan is still unwritten, and is what Linux and Android need".
  Um dos dois está desatualizado; tem de ser verificado no código antes de depender do backend.
- Útil para o marco: `tools/make_smoke_elf.py` gera um **título sintético** PPU (ELF64 BE com OPD,
  TLS, BSS e marcadores via `sys_tty_write`) para exercitar o loader do runtime sem jogo.

### 2.3 gow2-recomp (PS3, exemplo por jogo)

- Usa o **fork** `andrebrumdev/ps3recomp` (ramo `spurs-bringup`), não o upstream do sp00nznet. As
  correções Android/Vulkan estão nesse fork.
- Tem `android/` (NDK clang, SDL2, backend Vulkan, scripts de perf). **Resultado medido pelo autor**
  (não por mim): Galaxy Tab S9 FE (Mali-G68), gameplay p50 12 / p5 11 fps (1 corrida), gargalo na
  thread principal (PPU + walker RSX inline, ~90 % de um núcleo; GPU ~9 %). **Nunca foi medido em
  Adreno.** É a melhor prova pública de que a cadeia PPU+SPU → arm64 → Vulkan no Android é possível,
  e também mostra que o gargalo é CPU de thread única, não GPU.
- O kit dele descriptografa `EBOOT.BIN` com `.rap` (`tools/unself`). **Isso fica fora do
  recomp_android**: o pipeline aceitará só ELF já em claro fornecido pelo usuário; não
  implementaremos descriptografia nem manipulação de licenças.
- Perfil por jogo (`functions.json` com limites curados, jump tables e entradas no meio de função;
  hash PPU no formato do RPCS3) é o modelo a seguir para a Fase 2.

### 2.4 PS2Recomp (PS2)

- Módulos: `ps2xAnalyzer` (gera TOML), `ps2xRecomp` (decoder R5900 → C++, inclui MMI e macros VU0),
  `ps2xRuntime` (memória, dispatch, syscalls, GS/VU/IPU, **interpretador VU1** e VIF1),
  `ps2xIOP` (executa IRX R3000A com fallback HLE). Fluxo recomendado: Ghidra +
  `ExportPS2Functions.java`.
- Testes existentes (`ps2xTest/src`): decoder R5900, gerador de código, semântica de float PS2,
  VU/VU1, GS, SIF DMA/RPC, IOP, interrupções.
- **Android já existe**, mas: runner com **raylib (GLES), não Vulkan**; NDK 28.2, minSdk 28,
  ABIs arm64-v8a + x86_64; SIMD x86 traduzido por **sse2neon** em ARM. "Testado principalmente com
  MSVC" segundo o README. Logs do runtime ainda não vão para o logcat.
- Studio: preferir o **upstream ran-j**; o Studio é um fork parado.

---

## 3. O que cada ferramenta realmente consegue analisar (resumo)

| Formato | Ferramenta | Situação |
|---|---|---|
| ELF64 BE PowerPC (PPU, em claro) | ps3recomp `elf_parser.py`/`ppu_disasm.py`; Ghidra; objdump (binutils multiarch) | Suportado (observado na árvore) |
| SELF/EBOOT criptografado | — | **Fora de escopo** (DRM) |
| PRX (imports/exports por NID) | ps3recomp `prx_analyzer.py`, `nid_database.py` | Suportado |
| Imagens SPU embutidas | ps3recomp `extract_spu_images.py`, `spu_lifter.py` | Suportado |
| ELF MIPS R5900 (EE) | PS2Recomp; Ghidra + extensão EE (não verificado) | Suportado no PS2Recomp |
| Microprogramas VU1 | PS2Recomp: **interpretado** em runtime, não recompilado | Parcial |
| IRX (IOP R3000A) | PS2Recomp `ps2xIOP` (execução) | Parcial |

---

## 4. Licenças — o que pode ser combinado

- PS2Recomp é **GPL-3.0**; Armadasx3 é **GPL-2.0-only**. GPL-2.0-only e GPL-3.0 **não podem ser
  combinados no mesmo programa**. Portanto:
  - o pipeline PS2 (derivado do PS2Recomp) não pode receber código do Armadasx3/RPCS3;
  - o recomp_android não deve copiar arquivos do Armadasx3. O formato do `report.json` (uma ideia,
    não código) pode ser reimplementado; os arquivos `com.armadasx3.*` escritos pelo próprio
    usuário poderiam ser relicenciados por ele, se ele for o único autor (decisão do usuário).
- ps3recomp e gow2-recomp são MIT: compatíveis com GPL-3.0.
- **Proposta:** recomp_android sob **GPL-3.0-or-later**, com PS2Recomp e ps3recomp como
  dependências fixadas por commit (submódulo ou FetchContent), `THIRD_PARTY.md` com commit e
  licença de cada uma. Precisa da confirmação do usuário.
- Saídas geradas (C/C++ lifted a partir de um jogo) contêm material do jogo: ficam só na máquina
  do usuário, em diretório ignorado pelo git, e nunca vão para o repositório, CI ou artefatos.

---

## 5. Arquitetura proposta para o recomp_android

```
recomp_android/
  app/                    Android (Kotlin): UI, ciclo de vida, SAF, export de diagnóstico
  common/                 C/C++ compartilhado de verdade: entrada, arquivos, áudio (Oboe/AAudio),
                          apresentação Vulkan (swapchain, frame pacing), logs, report.json
  ps3/                    Pipeline PS3 — ps3recomp fixado + adaptação Android + backend Vulkan
  ps2/                    Pipeline PS2 — PS2Recomp fixado + adaptação Android + backend Vulkan
  games/<console>/<ID>/   Perfil por jogo (ID, região, versão, hashes, config de análise,
                          imports/símbolos/patches/hooks, cobertura, testes, regressões)
  analysis/               Exportações reproduzíveis do REA/Ghidra (só para homebrew/sintéticos
                          no repositório; para jogos, ficam locais)
  tests/                  equivalência de instruções, loader, runtime, smoke ARM64, Vulkan
  docs/
```

- PS2 e PS3 em bibliotecas nativas **separadas** (`libps2port.so`, `libps3port.so`), sem tradutor
  comum.
- Um port = um APK por jogo, compilado localmente pelo usuário a partir do seu dump (modelo do
  gow2-recomp). O CI só compila o runtime e os testes sintéticos.
- Backends D3D12/Metal do ps3recomp e GLES/raylib do PS2Recomp **não** são reutilizados como estão:
  o alvo é Vulkan 1.1+ no Adreno 740.

---

## 6. Plano incremental (cada marco tem um critério verificável)

Escala de resultado usada em todos os marcos: **compilou → instalou → abriu → carregou o perfil →
chegou ao menu → entrou em gameplay → passou no teste de estabilidade.** Nenhum marco usa
"funciona" sem dizer o nível.

### M0 — Esqueleto e CI (sem console)
App Android vazio + `common/` com logger e `report.json` (commit, build, ABI, Android, SoC, GPU,
driver e extensões Vulkan). CI: build `arm64-v8a` reproduzível com NDK fixado e testes de host.
**Critério:** APK compila no CI; testes de host verdes. (Abrir no aparelho: o usuário confirma.)

### M1-PS3 — Cadeia PPU mínima com binário sintético
1. Binário de teste: título sintético do `make_smoke_elf.py` + um ELF PPU escrito em assembly
   (montado aqui com `llvm-mc -triple=powerpc64`, disponível no container) cobrindo inteiros,
   CR/XER (carry/overflow/SO), loads/stores big-endian, desvios/`bctr`, chamada de syscall.
2. Análise: objdump e REA (provedor objdump/Rizin; Ghidra se instalado), exportando
   funções/endereços em JSON com evidência e confiança.
3. Lift com `ppu_lifter.py` fixado → C → host x86_64 e NDK arm64.
4. Testes de equivalência por instrução contra valores de referência; oráculo de execução: o
   mesmo ELF no Armadasx3/RPCS3 (interpretador PPU) comparando registradores e memória finais.
**Critério:** mesmos resultados no host e no oráculo; `.so` arm64 compilado; no aparelho, marcadores
no logcat e `report.json` exportado (confirmação do usuário).

### M2-PS3 — SPU e DMA sintéticos
Programa SPU pequeno (DMA get/put, canais, mailbox) lançado pelo PPU. Testes de equivalência de
operações de 128 bits e de sincronização. RSX continua fora.

### M1-PS2 — Cadeia EE mínima com binário sintético
ELF MIPS montado com `llvm-mc -triple=mips64el` mais palavras MMI/128 bits codificadas à mão
(o LLVM não codifica MMI do R5900). PS2Recomp fixado → C++ → host e NDK arm64 (sse2neon).
Testes de equivalência: MMI (PADDW, PEXTLW, PCPYLD…), `MULT1/DIV1`, overflow de `ADD`, float PS2
(sem NaN/Inf), loads/stores de 128 bits. Rodar a suíte `ps2xTest` existente no arm64.
**Critério igual ao M1-PS3.**

### M2-PS2 — VU0/VU1, DMA e GS mínimo
Microprograma VU1 sintético via VIF1, saída comparada com valores esperados; GS: limpar tela e
desenhar um triângulo via Vulkan.

### M3 — Backend Vulkan no Android (por console)
PS3: RSX (FIFO → Vulkan), verificando antes a inconsistência do §2.2 e reaproveitando o caminho
Vulkan do fork do gow2-recomp, se a licença e a qualidade permitirem. PS2: GS → Vulkan no lugar do
raylib. Testes com a camada de validação e captura de frametime/1 % lows.

### Fase 2 — Primeiro jogo (escolha do usuário)
Perfil em `games/`, dump legal fornecido pelo usuário, análise local, cobertura de funções/stubs
acionados registrada, e a escala de resultado reportada honestamente. Benchmark A/B com cache frio
e quente identificados.

---

## 7. Decisões que dependem do usuário

**Respondidas em 2026-10-17:**

1. Licença: **GPL-3.0-or-later** (arquivo `LICENSE`).
2. Console: **PS3** (o usuário corrigiu "p23" para "ps3"). O PS2 fica adiado.
3. REA com jogos comerciais: o usuário **aceita explicitamente** que dados derivados (pseudocódigo,
   assembly, nomes, endereços) vão para o provedor do agente. Os **binários e assets do jogo
   continuam fora**: nada de upload do dump, e nada de código lifted no repositório.

Texto original das perguntas:

1. **Licença** do recomp_android (proposta: GPL-3.0-or-later; ver §4).
2. **Console do primeiro marco:** PS3 (mais perto do Armadasx3 e com prova pública no Android via
   gow2-recomp) ou PS2 (PS2Recomp já tem runner Android). Proposta: PS3 primeiro, PS2 em seguida,
   sem misturar código.
3. **REA com jogos comerciais:** rodar localmente com modelo local, ou aceitar explicitamente o envio
   de dados derivados ao provedor do agente. Sem essa decisão, só homebrew/sintéticos.
4. **Primeiro jogo da Fase 2** (ID, região, versão) — só depois de M1/M2.

## 8. Limitações deste ambiente (observado)

- Sem Android SDK/NDK, sem `adb`, sem aparelho: nada pode ser instalado ou medido no Odin 2 Portal
  daqui. Testes no aparelho dependem do usuário.
- Sem Ghidra, Rizin, Hopper ou IDA; REA não instalado ainda.
- Disponível: clang/LLVM 18 com alvos `ppc64` e `mips*`/`aarch64`, `llvm-mc`, `ld.lld`, objdump,
  CMake, Ninja, Python 3, Node 22.22, Java.
- Nenhuma métrica de desempenho deste documento foi medida por mim; as citadas vêm dos READMEs dos
  projetos, com a fonte indicada.
