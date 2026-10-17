# recomp_android

Ports nativos para Android de jogos específicos de PS2 e PS3, por **recompilação estática (AOT)**.
Alvo inicial: **AYN Odin 2 Portal** (Snapdragon 8 Gen 2, Adreno 740, Android ARM64, Vulkan).

> Estado atual: **M0 (esqueleto)**. Ainda não existe pipeline de PS2 nem de PS3, e nenhum jogo roda.
> Veja [Marcos](#marcos).

O projeto não inclui nem distribui jogos, BIOS, firmware, chaves ou executáveis comerciais.
Você fornece o seu próprio dump, obtido legalmente. O código C/C++ gerado a partir dele fica só
na sua máquina e nunca entra neste repositório. Descriptografia e contorno de DRM estão fora de
escopo.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `app/` | App Android (Kotlin, sem dependências além do SDK): UI, ciclo de vida, exportação do diagnóstico |
| `app/src/main/cpp/` | Ponte JNI → `librecompandroid.so` |
| `common/` | C++ compartilhado pelos dois consoles: log, `report.json`, inventário Vulkan |
| `tests/host/` | Testes de host (sem dependências) e o CLI `recomp-report` |
| `tools/check_report.py` | Validador do `report.json` (também aceita o ZIP exportado) |
| `docs/` | [Fase 0](docs/FASE0-AUDITORIA.md), [build](docs/BUILD.md), [diagnóstico](docs/DIAGNOSTICO.md) |

Os pipelines `ps2/` e `ps3/` serão independentes (M1+). Nada específico de um console entra em
`common/`.

## Build rápido

```sh
# Host: testes (precisa de libvulkan-dev; mesa-vulkan-drivers para o teste real do Vulkan)
cmake -S . -B build -G Ninja && cmake --build build && ctest --test-dir build

# Android: APK arm64-v8a (NDK 29.0.14206865, CMake 3.30.5, JDK 17+)
./gradlew :app:assembleRelease :app:testDebugUnitTest
```

Detalhes e versões fixadas em [`docs/BUILD.md`](docs/BUILD.md).

## Marcos

Escala usada para todo resultado: **compilou → instalou → abriu → carregou o perfil → chegou ao
menu → entrou em gameplay → passou no teste de estabilidade.**

| # | Marco | Estado |
|---|---|---|
| Fase 0 | Auditoria e plano | Concluída ([relatório](docs/FASE0-AUDITORIA.md)) |
| M0 | Esqueleto Android + `common/` + CI | **Compilou** (APK arm64-v8a e testes de host/JVM verdes localmente). Instalar/abrir no Odin 2 Portal: **não verificado** |
| M1-PS3 | PPU sintético → lift → arm64 | Não iniciado |
| M1-PS2 | EE (R5900) sintético → lift → arm64 | Não iniciado |
| M2 | SPU/DMA (PS3), VU/GS mínimo (PS2) | Não iniciado |
| M3 | Backend Vulkan por console | Não iniciado |

## Licença

GPL-3.0-or-later ([`LICENSE`](LICENSE)). Componentes de terceiros e seus commits:
[`THIRD_PARTY.md`](THIRD_PARTY.md).
