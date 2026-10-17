# Terceiros

## Código incluído neste repositório

Nenhum. O M0 é código original.

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
| sp00nznet/ps3recomp | `39a36296511c445707adabcd312f0b740cfbd694` | MIT | pipeline PS3 (M1-PS3) |
| andrebrumdev/gow2-recomp | `a787912c7b2e2f61bb387c9c22722a93e6c5ee3c` | MIT | referência de port por jogo e de Android/Vulkan |
| morluto/rea | `3fa972af7c7cb6cf014ffc426bdf7130dc6f2fd2` (v6.5.0) | MIT | análise assistida (ferramenta externa, não é ligada ao app) |

O Armadasx3 (GPL-2.0-only) é usado só como oráculo de comportamento, rodando separadamente.
O código dele não pode ser combinado com o código GPL-3.0 deste projeto.
