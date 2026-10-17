// SPDX-License-Identifier: GPL-3.0-or-later
//
// recomp_android app shell. Kotlin is AGP 9's built-in support; no Kotlin plugin is applied.
// The native library (librecompandroid.so) is built here by CMake from app/src/main/cpp,
// which pulls in ../common. Console pipelines will be separate libraries (M1+).
plugins {
    alias(libs.plugins.android.application)
}

// One commit for the APK and its native code: CMake receives it instead of asking git itself.
val gitCommit: String = providers.exec {
    commandLine("git", "rev-parse", "HEAD")
    isIgnoreExitValue = true
}.standardOutput.asText.get().trim().ifEmpty { "unknown" }

android {
    namespace = "io.github.rickamaral94.recompandroid"
    compileSdk = 37
    ndkVersion = "29.0.14206865"

    defaultConfig {
        applicationId = "io.github.rickamaral94.recompandroid"
        minSdk = 31
        targetSdk = 37
        versionCode = 1
        versionName = "0.0.1"

        buildConfigField("String", "GIT_COMMIT", "\"$gitCommit\"")

        ndk {
            abiFilters.add("arm64-v8a")
        }
        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DANDROID_STL=c++_static",
                    "-DRECOMP_GIT_COMMIT=$gitCommit",
                    "-DRECOMP_VERSION=0.0.1",
                )
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.30.5"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Test build: signed with the debug key so it installs without a keystore.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

dependencies {
    testImplementation(libs.junit)
}
