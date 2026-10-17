# Build

## Versões fixadas

| Item | Versão | Onde |
|---|---|---|
| NDK | 29.0.14206865 | `app/build.gradle.kts` (`ndkVersion`), CI |
| CMake (Android) | 3.30.5 | `app/build.gradle.kts`, CI |
| Gradle | 9.4.1 | `gradle/wrapper/gradle-wrapper.properties` (com SHA-256) |
| AGP | 9.2.1 | `gradle/libs.versions.toml` |
| compileSdk / targetSdk / minSdk | 37 / 37 / 31 | `app/build.gradle.kts` |
| Build-tools | 36.0.0 (padrão do AGP) e 37.0.0 (apksigner/zipalign no CI) | CI |
| JDK | 17+ (CI usa Temurin 21) | |
| ABI | somente `arm64-v8a` | |

É a mesma combinação de NDK/CMake/Gradle/AGP que o Armadasx3 usa no CI.

## Host (testes)

```sh
sudo apt-get install ninja-build libvulkan-dev mesa-vulkan-drivers
cmake -S . -B build -G Ninja
cmake --build build
RECOMP_EXPECT_VULKAN=1 ctest --test-dir build --output-on-failure
./build/tests/host/recomp-report > build/report.json && python3 tools/check_report.py build/report.json
```

`RECOMP_EXPECT_VULKAN=1` faz o teste exigir um dispositivo Vulkan (lavapipe no CI). Sem a
variável, o teste só confere que a falha vem com um motivo.

## Android

```sh
export ANDROID_HOME=/caminho/do/sdk
sdkmanager "ndk;29.0.14206865" "cmake;3.30.5" "platforms;android-37.0" "build-tools;36.0.0" "build-tools;37.0.0"
./gradlew :app:assembleRelease :app:testDebugUnitTest
adb install -r app/build/outputs/apk/release/app-release.apk
```

O APK de release é assinado com a chave **debug**: é uma build de teste, não uma distribuição.
O commit de `git rev-parse HEAD` vai para o `BuildConfig` e para o código nativo
(`-DRECOMP_GIT_COMMIT`), e o CI confere que é o commit que está sendo compilado.

### Maven Central com limite de requisições

Se o Gradle receber HTTP 429 de `repo.maven.apache.org`, use um init script local que redirecione
para o espelho do Google (`https://maven-central.storage-download.googleapis.com/maven2/`).
O repositório continua usando `mavenCentral()`.

## Verificações do CI (`.github/workflows/ci.yml`)

- host: gcc e clang, `-Wall -Wextra -Werror`, testes e validação do `report.json`;
- Android: APK + testes JVM; o `.so` é aarch64, tem todos os segmentos LOAD alinhados em 16 KB,
  exporta os símbolos JNI e contém o commit do build; `apksigner verify`; `zipalign -c -P 16`.
