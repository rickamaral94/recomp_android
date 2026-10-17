# M1-PS3 — PPU sintético → lift → arm64, com oráculo

Estado em 2026-10-17. Escopo: **instruções inteiras da PPU** (sem FP, VMX, syscalls, SPU, RSX).
Nada disso envolve código de jogo: o binário de teste é gerado.

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

## Resultado (execução local de 2026-10-17)

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
- **FP, VMX, reservas atômicas** (`lwarx`/`stwcx.`), `mftb`, syscalls e chamadas indiretas
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

1. FP (`fadd`, `fmadd`, `fctiw`, `frsp`, NaN/arredondamento) e VMX com `-cpu 970`, que tem AltiVec.
   No VMX, cuidado com o modo non-Java (NJ) do Cell.
2. `lwarx`/`stwcx.` e `ldarx`/`stdcx.`, `mftb`, `bctr`/`bctrl` com um despachante de teste.
3. Um ELF no formato PS3 (OPD, TOC, imports) com `make_smoke_elf.py` do ps3recomp, passando pelo
   loader do runtime.
4. Rodar o harness arm64 no Odin 2 Portal (adb ou dentro do app) para sair do qemu.
