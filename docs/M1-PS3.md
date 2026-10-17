# M1-PS3 — PPU sintético → lift → arm64, com oráculo

Estado em 2026-10-17. Escopo: **instruções inteiras, de ponto flutuante (FP) e vetoriais
(VMX/AltiVec) da PPU**. Ficam de fora syscalls, SPU e RSX. Nada disso envolve código de jogo:
o binário de teste é gerado.

Três suítes (`gen_cases.py --suites int,fp,vmx`), com 34.461 casos ao todo:

| Suíte | Casos | Entradas | Registro |
|---|---|---|---|
| int | 23.350 | r4–r6, CR, XER | r7, r8, CR, XER |
| fp | 5.654 | f1–f3, FPSCR[RN] | f7, f8, CR, FPSCR (só informativo) |
| vmx | 5.457 | v4–v6, VSCR (NJ, SAT) | v7, CR, VSCR |

## O que o teste faz

`tests/ps3/ppu_diff/` compara, byte a byte, **as mesmas instruções** executadas de três formas:

| Alvo | Como roda |
|---|---|
| Oráculo | Kernel PPC64 big-endian, ligado num ELF estático e executado em `qemu-ppc64 -cpu power7` |
| Host | Os mesmos bytes, recompilados pelo `ppu_lifter.py` do ps3recomp (`third_party/ps3recomp` @ `39a36296`) para C++, compilados com clang no x86_64 |
| Android arm64 | O mesmo C++, compilado com o NDK `29.0.14206865` (`aarch64-linux-android31`, estático) e executado em `qemu-aarch64` |

Por que POWER7: o Cell PPU segue a ISA 2.02 e tem também `ldbrx`/`stdbrx`. O POWER5+ (ISA 2.02)
não tem essas duas e gera SIGILL, o que foi verificado aqui. O POWER7 (ISA 2.06) tem as duas e
ainda não tem os bits OV32/CA32 da ISA 3.0, que o Cell também não tem. O kernel não usa nenhuma
instrução ausente no Cell.

Cada caso carrega entradas conhecidas (r4–r6, CR, XER), executa uma instrução ou uma sequência
curta e grava r7, r8, CR e XER. Ao fim também se compara a memória de rascunho (256 bytes).
Os casos ficam em 75 funções chamadas por `bl` a partir de uma função principal, o que também
cobre chamada e retorno entre funções recompiladas.

Os campos que a ISA deixa **indefinidos** são mascarados caso a caso, e só eles: a palavra alta
de `mulhw`/`mulhwu`/`divw`/`divwu` em modo 64 bits, LT/GT/EQ do CR0 nesses casos e o resultado de
divisão por zero ou com overflow. As flags OV/SO desses casos continuam sendo comparadas.

## Resultado (execução local de 2026-10-17, três suítes)

| Alvo | Casos | Iguais ao oráculo | Divergências conhecidas | Sem explicação | Memória |
|---|---|---|---|---|---|
| host x86_64 (clang 18, `-O1`) | 34.461 | 34.317 | 144 | **0** | igual |
| android-arm64 (NDK 29, `-O1`, qemu-aarch64) | 34.461 | 34.329 | 132 | **0** | igual |

A suíte de inteiros continua 100% igual nos dois alvos. Todas as diferenças estão em FP e VMX,
e cada uma está explicada em `tests/ps3/ppu_diff/known_divergences.json`, com o número exato de
casos por alvo. O CI reprova se aparecer uma falha fora da lista ou se algum desses números
mudar.

### Divergências encontradas no ps3recomp `39a36296`

| Id | Classe | O que acontece | Casos (x86_64 / arm64) |
|---|---|---|---|
| `fp-rounding-mode-ignored` | lifter | `FPSCR[RN]` ≠ "mais próximo" é ignorado por `fadd`/`fmul`/`fdiv`/`fadds`/`fmuls`/`fmadd`/`frsp`/`fctiw`/`fctid`/`fcfid` | 56 / 56 |
| `fsqrt-default-nan-sign-x86` | lifter | `fsqrt` de negativo devolve o NaN padrão do host: `0xfff8…` no x86. No arm64 é `0x7ff8…`, igual ao PowerPC | 12 / **0** |
| `lfs-quiets-snan` | lifter | `lfs` de sNaN simples liga o bit "quiet" | 2 / 2 |
| `stfs-rounds-instead-of-bit-conversion` | lifter | `stfs` usa um cast `(float)`, que arredonda, estoura para inf e silencia sNaN. A ISA manda recortar os bits | 6 / 6 |
| `vmx-fma-snan-payload` | lifter | `vmaddfp`/`vnmsubfp` com sNaN perdem o payload (`0x7fc00000` em vez de `0x7fc00001`) | 48 / 48 |
| `vctuxs-sat-on-negative-fraction` | lifter | `vctuxs` de um valor em (−1, 0) liga `VSCR[SAT]`; o vetor resultante está certo | 2 / 2 |
| `vcmpfp-nj-denormal-not-flushed` | lifter | com NJ=1, as comparações de float vetoriais não zeram os operandos denormais. O manual do Cell manda zerar (ver abaixo) | 18 / 18 |

Impacto esperado num jogo (inferência, a confirmar no ELF):
- **Baixo:** jogos quase nunca mudam o modo de arredondamento, carregam sNaN ou leem o SAT.
- **Primeiro a corrigir:** o `stfs` de double não arredondado. Um compilador normalmente faz
  `frsp` antes, mas não há garantia. A análise do executável vai mostrar se existe `mtfsf`/`mtfsfi`
  e `stfs` sem `frsp` antes.

O FPSCR é gravado mas não comparado: o próprio ps3recomp diz que a aritmética FP ainda não
atualiza os bits de status, e o qemu os atualiza (eles diferem em 5.101 casos de FP). As formas
FP com ponto (CR1 vem do FPSCR) ficaram de fora pelo mesmo motivo. Também ficaram de fora as
estimativas (`fres`, `frsqrte`, `vrefp`, `vrsqrtefp`, `vexptefp`, `vlogefp`), cujo resultado
exato depende do processador, e as instruções exclusivas do Cell (`lvlx`/`lvrx`/`stvlx`/`stvrx`),
que o POWER7 não tem.

Na primeira rodada, 37 falhas de `vsl`/`vsr` eram **erro meu**: a ISA só define o resultado
quando todos os bytes do vetor de deslocamento são iguais. O gerador agora usa contagens
replicadas em todos os bytes.

## Segundo oráculo: interpretador do RPCS3

`run_rpcs3_oracle.py` empacota o mesmo kernel num ELF de PS3 (`ps3_elf.py`) e o roda no RPCS3
de desktop, sem interface gráfica e sem firmware.

- **Versão:** RPCS3 upstream `26098fb42d090cd522b4afcf3b754dd987c82978` (2026-10-10), o commit
  com que o Armadasx3 está sincronizado.
- **Configuração:** só o interpretador estático (build sem LLVM), com todas as opções de
  precisão da PPU ligadas: Set Saturation Bit, Accurate Non-Java Mode, Set FPCC Bits, Accurate
  Vector NaN Values, Vector NaN Handling, Accurate DFMA, Accurate Vector Estimates.
- **Bibliotecas:** as 76 bibliotecas de firmware que o RPCS3 carrega em LLE por padrão ficam em
  HLE, porque o kernel não importa nenhuma.
- **Saída:** os resultados voltam em hexadecimal pela TTY. O stub de saída foi conferido no qemu,
  com bytes idênticos ao `oracle.bin`.
- **Build:** `tools/oracle/build_rpcs3.sh` reproduz o build com todos os ajustes. O RPCS3
  (GPL-2.0-only) roda como programa separado e não é ligado ao projeto.

Resultado (execução local de 2026-10-17, 8 s):

| Comparação | Casos iguais |
|---|---|
| qemu-ppc64 × RPCS3 | 33.699 / 34.461 |
| recompilado x86_64 × RPCS3 | 33.843 / 34.461 |
| recompilado arm64 × RPCS3 | 33.831 / 34.461 |

O que se conclui:

1. **Inteiros e VMX:** fora das divergências conhecidas, os três (qemu, RPCS3 e código
   recompilado) concordam em todos os casos.
2. **Divergências conhecidas:** nas sete, o RPCS3 dá o mesmo resultado que o código recompilado.
   Isso não valida nenhum dos dois, só mostra que fazem as mesmas simplificações. Cada entrada
   de `known_divergences.json` registra o veredito do RPCS3 no campo `rpcs3`.
3. **NaN em FP escalar:** em 630 casos o RPCS3 discorda tanto do qemu quanto do código
   recompilado, que concordam entre si. O padrão é sempre o mesmo: o NaN padrão de operação
   inválida sai `0xfff8…`, o do x86 hospedeiro, e `fmsub`/`fnmadd`/`fnmsub` invertem o sinal de um
   NaN propagado. A ISA diz que a negação não se aplica a NaN. Conclusão: nos bits de NaN em FP
   escalar, o interpretador do RPCS3 no x86 **não serve de referência**.
4. **NJ nas comparações de vetor:** resolvido pela documentação, não pelo voto dos oráculos. O
   *Vector/SIMD Multimedia Extension Technology Programming Environments Manual*, edição do Cell
   (v2.07c, 2006-10-26), seção 3.2.1.2 "Non-Java Mode", diz: "denormalized input operands are
   flushed to the correctly signed zero (±0.0) before being used by the instruction". A página
   do `vcmpbfp` repete isso. O qemu segue o manual; o RPCS3 (mesmo com Accurate Non-Java Mode) e
   o ps3recomp não. Confiança alta para o `vcmpbfp`, média-alta para as outras três. Sem teste
   em hardware.

Ainda não testado contra o RPCS3: as instruções que o qemu não tem (`lvlx`/`lvrx`/`stvlx`/`stvrx`)
e as estimativas (`fres`, `frsqrte`, `vrefp`, `vrsqrtefp`). Para estas, o RPCS3 diz ser "hardware
exact" com Accurate Vector Estimates. Elas precisam de uma suíte própria que só rode no RPCS3.

O oráculo RPCS3 ainda não roda no CI: o build leva cerca de 40 minutos sem cache. Hoje roda
localmente com `build_rpcs3.sh` + `run_rpcs3_oracle.py`.

### Suíte de inteiros (primeira versão deste marco)

| Alvo | Casos | Iguais ao oráculo | Memória de rascunho |
|---|---|---|---|
| host x86_64 (clang 18, `-O1`) | 23.350 | **23.350** | igual |
| android-arm64 (NDK 29, `-O1`, sob qemu-aarch64) | 23.350 | **23.350** | igual |

São 116 grupos de instruções:
- **Soma, subtração e carry:** `add`, `addc`, `adde`, `subf`, `subfc`, `subfe`, `addze`, `addme`, `subfze`, `subfme`, `neg`, `addic`, `subfic` e as formas com `o`/`.`.
- **Multiplicação e divisão:** `mul*`, `div*`.
- **Lógicas e extensão de sinal:** `and`, `or`, `xor`, `nand`, `nor`, `eqv`, `andc`, `orc`, as formas imediatas, `extsb`/`extsh`/`extsw`, `cntlzw`/`cntlzd`.
- **Deslocamentos e rotações:** `slw`, `srw`, `sraw`, `srawi`, `sld`, `srd`, `srad`, `sradi`, `rlw*`, `rld*`.
- **Comparações:** `cmp*`, em CR0, CR3 e CR7, com SO ligado e desligado.
- **Lógica de CR:** `cr*`, `mcrf`, `mtcrf`.
- **Loads e stores:** todos os tamanhos, com sinal, indexados, com update, desalinhados e com bytes invertidos (`lhbrx`, `lwbrx`, `ldbrx`, `sthbrx`, `stwbrx`, `stdbrx`).
- **Desvios:** condicionais em cada bit de CR0/CR1 e laços de CTR (`bdnz`, `bdz`, `bdnzt`, `bdnzf`).

Tempos dessa execução: geração 0,9 s, montagem 1,9 s, oráculo 0,5 s, lift 11 s, build host 24 s,
build arm64 41 s, execução arm64 no qemu 1 s.

### O teste consegue reprovar? (`mutation_check.py`)

Defeitos injetados de propósito no código recompilado. Cada um é aplicado no primeiro ponto de
cada arquivo e depois em todos os pontos:

| Mutante | Detectado |
|---|---|
| carry calculado com `<=` em vez de `<` | sim (3 e 366 casos diferentes) |
| forma com ponto deixa de copiar XER[SO] para o CR0 | sim (25 e 7.057 casos) |
| stores em little-endian no runtime | sim (21.934 casos) |

Na primeira rodada, o segundo mutante **escapou** quando aplicado num único ponto: o caso
afetado só rodava com SO desligado. Corrigido no gerador: toda forma com ponto ganha
automaticamente um caso com SO ligado.

## O que isto prova e o que não prova

Prova que, para essas instruções e entradas, o lifter do ps3recomp gera C que dá o mesmo
resultado que uma CPU PowerPC (via qemu), compilado tanto para x86_64 quanto para arm64.

Não prova:
- **Cell real:** o oráculo é o qemu, não um Cell. As diferenças conhecidas entre eles estão nas
  partes mascaradas. Comparar com o interpretador do RPCS3/Armadasx3 é o próximo oráculo.
- **Aparelho:** o binário arm64 rodou em qemu-aarch64, não no Odin 2 Portal.
- **Flags do FPSCR, estimativas e instruções exclusivas do Cell:** fora (veja acima).
- **Reservas atômicas** (`lwarx`/`stwcx.`), `mftb`, syscalls e chamadas indiretas
  (`bctr`/`bctrl`): fora deste teste. O harness aborta se alguma for chamada.
- **Código de jogo:** fluxo de controle real, jump tables, entradas no meio de função, TOC e OPD
  ainda não foram exercitados.

Nível na escala do projeto: o teste **compilou** e **passou no host e no arm64 emulado**. Nada
foi instalado nem executado no aparelho.

## Como rodar

```sh
sudo apt-get install clang lld llvm qemu-user
git submodule update --init third_party/ps3recomp
python3 tests/ps3/ppu_diff/run_diff.py --build build-ppu-diff --ndk "$ANDROID_HOME/ndk/29.0.14206865"
python3 tests/ps3/ppu_diff/mutation_check.py build-ppu-diff
```

`build-ppu-diff/report.json` lista cada caso que diverge: entradas, campos e os valores do
oráculo e do código recompilado.

## Próximos passos

1. Suíte só para o RPCS3: `lvlx`/`lvrx`/`stvlx`/`stvrx` e estimativas.
2. Corrigir as divergências que o ELF do jogo mostrar que importam (patches no ps3recomp,
   enviados também para o upstream).
3. `lwarx`/`stwcx.` e `ldarx`/`stdcx.`, `mftb`, `bctr`/`bctrl` com um despachante de teste.
4. Um ELF no formato PS3 (OPD, TOC, imports) com `make_smoke_elf.py` do ps3recomp, passando pelo
   loader do runtime.
5. Rodar o harness arm64 no Odin 2 Portal (adb ou dentro do app) para sair do qemu.
