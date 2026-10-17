# Terceiros

## Código incluído neste repositório

| Componente | Commit | Licença | Uso |
|---|---|---|---|
| sp00nznet/ps3recomp (submódulo `third_party/ps3recomp`) | `39a36296511c445707adabcd312f0b740cfbd694` | MIT | `tools/ppu_lifter.py` e os cabeçalhos de `runtime/ppu` no teste diferencial (M1-PS3); nada dele vai no APK ainda. Os patches de `patches/ps3recomp/` modificam esse código (ver o README de lá) |

## Dependências de build (baixadas, não versionadas aqui)

| Componente | Versão | Licença | Uso |
|---|---|---|---|
| Android Gradle Plugin | 9.2.1 | Apache-2.0 | build do app |
| Gradle (wrapper) | 9.4.1 (SHA-256 `2ab2958f…7ec6cb`) | Apache-2.0 | build |
| Android NDK | 29.0.14206865 | Apache-2.0 e outras (ver NDK) | código nativo; inclui os cabeçalhos Vulkan usados no Android |
| JUnit | 4.13.2 | EPL-1.0 | só testes JVM, não vai no APK |
| Vulkan-Headers (pacote `libvulkan-dev` do sistema) | 1.3.275 no Ubuntu 24.04 | Apache-2.0 / MIT | só build de host |

## Referências planejadas (ainda não usadas)

Auditadas na [Fase 0](docs/FASE0-AUDITORIA.md). Nenhum código delas foi copiado até agora. Quando
for, o commit fixado e a licença entram nesta tabela.

| Projeto | Commit auditado | Licença | Uso previsto |
|---|---|---|---|
| ran-j/PS2Recomp | `eb8688b2fd191129f103a39543002c005b33409c` | GPL-3.0 | pipeline PS2 (M1-PS2) |
| andrebrumdev/gow2-recomp | `a787912c7b2e2f61bb387c9c22722a93e6c5ee3c` | MIT | referência de port por jogo e de Android/Vulkan |
| morluto/rea | `3fa972af7c7cb6cf014ffc426bdf7130dc6f2fd2` (v6.5.0) | MIT | análise assistida (ferramenta externa, não é ligada ao app) |

Ferramentas externas usadas só como programas separados, nunca ligadas ao projeto:

| Ferramenta | Versão | Licença | Uso |
|---|---|---|---|
| RPCS3 | `26098fb42d090cd522b4afcf3b754dd987c82978` | GPL-2.0-only | segundo oráculo da PPU (`tools/oracle/build_rpcs3.sh`, `tests/ps3/ppu_diff/run_rpcs3_oracle.py`) |
| Qt (via aqtinstall, download.qt.io) | 6.9.3 | LGPL-3.0 | só para compilar o RPCS3 do oráculo |
| qemu-user | 8.2.2 (Ubuntu) | GPL-2.0 | oráculo qemu-ppc64 e execução do binário arm64 nos testes |

O Armadasx3 (GPL-2.0-only) é usado só como oráculo de comportamento, rodando separadamente.
O código dele não pode ser combinado com o código GPL-3.0 deste projeto.
